from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, Tk, Toplevel, filedialog, messagebox, simpledialog, ttk

from tools.orion_development_console.comparison import compare_checkpoints, render_comparison
from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.engine import VerificationEngine
from tools.orion_development_console.memory import AmbiguousTaskRecall, DevelopmentMemoryService
from tools.orion_development_console.memory_models import DevelopmentCheckpoint, PromptRecord
from tools.orion_development_console.models import VerificationReport
from tools.orion_development_console.presentation import SUBJECT_TITLES, presentation_rows
from tools.orion_development_console.theme import PALETTE, apply_orion_development_theme, status_group


NAVIGATION = (
    ("overview", "OVERVIEW"),
    ("roadmap", "ROADMAP · PHASE 3"),
    ("history", "HISTORY"),
    ("guard", "GUARD"),
    ("evidence", "EVIDENCE"),
    ("system", "SYSTEM"),
)


class DevelopmentConsoleApp:
    """Separate dev-only ORION-family UI; never starts the production runtime."""

    def __init__(
        self,
        root: Tk,
        engine: VerificationEngine,
        memory: DevelopmentMemoryService | None = None,
    ) -> None:
        self.root = root
        self.engine = engine
        self.memory = memory or DevelopmentMemoryService(engine.context, engine=engine)
        self.report: VerificationReport | None = engine.cached_report()
        self.current_page = "overview"
        self.page_title = tk.StringVar(value="OVERVIEW")
        self._result_queue: queue.SimpleQueue[VerificationReport | BaseException] = queue.SimpleQueue()
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.checkpoint_tree: ttk.Treeview | None = None
        self.prompt_tree: ttk.Treeview | None = None
        self.root.title("ORION Development Console")
        self.root.geometry("1200x780")
        self.root.minsize(1000, 650)
        apply_orion_development_theme(self.root, engine.context.repository_root)
        self._build_shell()
        self.show_page("overview")

    def _build_shell(self) -> None:
        outer = ttk.Frame(self.root, style="Orion.TFrame")
        outer.pack(fill=BOTH, expand=True)
        sidebar = ttk.Frame(outer, style="Panel.TFrame", width=248)
        sidebar.pack(side=LEFT, fill=Y)
        sidebar.pack_propagate(False)
        brand = ttk.Frame(sidebar, style="Panel.TFrame")
        brand.pack(fill=X, padx=20, pady=(22, 18))
        ttk.Label(brand, text="ORION", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(brand, text="DEVELOPMENT CONSOLE", style="BrandSub.TLabel").pack(anchor="w", pady=(1, 0))
        ttk.Separator(sidebar).pack(fill=X, padx=16, pady=(0, 12))
        nav = ttk.Frame(sidebar, style="Panel.TFrame")
        nav.pack(fill=X)
        for key, caption in NAVIGATION:
            button = ttk.Button(nav, text=caption, style="Nav.TButton", command=lambda page=key: self.show_page(page))
            button.pack(fill=X, padx=10, pady=2)
            self.nav_buttons[key] = button
        footer = ttk.Frame(sidebar, style="Panel.TFrame")
        footer.pack(side="bottom", fill=X, padx=18, pady=18)
        ttk.Label(footer, text="DEVELOPMENT TOOL", style="BrandSub.TLabel").pack(anchor="w")
        ttk.Label(footer, text="Separate from Launcher\nPrivate local records\nManual prompt copy only", style="PanelMuted.TLabel", justify="left").pack(anchor="w", pady=(4, 0))

        main = ttk.Frame(outer, style="Orion.TFrame")
        main.pack(side=RIGHT, fill=BOTH, expand=True)
        header = ttk.Frame(main, style="Orion.TFrame")
        header.pack(fill=X, padx=30, pady=(20, 10))
        title = ttk.Frame(header, style="Orion.TFrame")
        title.pack(side=LEFT)
        ttk.Label(title, text="ORION DEVELOPMENT CONSOLE", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(title, textvariable=self.page_title, style="Title.TLabel").pack(anchor="w")
        ttk.Button(header, text="REFRESH VIEW", style="Secondary.TButton", command=self._refresh_page).pack(side=RIGHT, pady=(8, 0))
        self.status_strip = ttk.Frame(main, style="Status.TFrame", padding=(16, 10))
        self.status_strip.pack(fill=X, padx=30, pady=(0, 14))

        viewport = ttk.Frame(main, style="Orion.TFrame")
        viewport.pack(fill=BOTH, expand=True, padx=(30, 12), pady=(0, 24))
        self.canvas = tk.Canvas(viewport, bg=PALETTE["background"], highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", style="Main.Vertical.TScrollbar", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.content = ttk.Frame(self.canvas, style="Orion.TFrame")
        self.content_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.content_window, width=event.width))
        self.canvas.bind("<Enter>", lambda _event: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda _event: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event: tk.Event) -> str:
        self.canvas.yview_scroll((-1 if event.delta > 0 else 1) * 3, "units")
        return "break"

    def _clear(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _refresh_page(self) -> None:
        self.report = self.engine.cached_report()
        self.show_page(self.current_page)

    def show_page(self, page: str) -> None:
        self.current_page = page
        self.page_title.set(dict(NAVIGATION)[page])
        for key, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if key == page else "Nav.TButton")
        self._render_status_strip()
        self._clear()
        getattr(self, f"_page_{page}")()
        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(0.0)

    def _status_cell(self, name: str, value: str) -> None:
        cell = ttk.Frame(self.status_strip, style="Status.TFrame")
        cell.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(cell, text=name, style="StatusName.TLabel").pack(anchor="w")
        group = status_group(value.split(" ")[0])
        ttk.Label(cell, text=value, style=f"Status{group.title()}.TLabel").pack(anchor="w", pady=(1, 0))

    def _render_status_strip(self) -> None:
        for child in self.status_strip.winfo_children():
            child.destroy()
        guard = self.memory.guard_report()
        git = self.memory.current_git()
        self._status_cell("ARCHITECTURE GUARD", f"{guard.get('gate', 'UNKNOWN')} · {guard.get('report_id', 'NONE')}")
        self._status_cell("LOCAL ENVIRONMENT", self.report.overall_state.value if self.report else "NOT_CHECKED")
        self._status_cell("GIT", f"{git.get('branch', 'UNKNOWN')} · {str(git.get('head', ''))[:7]}")

    def _card(self, parent: ttk.Frame, title: str, value: str, *, width: int = 760) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, text=value, style="CardText.TLabel", wraplength=width, justify="left").pack(anchor="w", pady=(5, 0))
        return card

    def _page_overview(self) -> None:
        checkpoint = self.memory.latest_checkpoint()
        prompt = self.memory.latest_prompt()
        git = self.memory.current_git()
        evidence = self.report.observation("evidence") if self.report else None
        stage = checkpoint.development_stage if checkpoint else "NOT RECORDED"
        next_step = checkpoint.approved_next_step if checkpoint and checkpoint.approved_next_step else "USER CONFIRMATION REQUIRED"
        hero = ttk.Frame(self.content, style="CardAlt.TFrame", padding=22)
        hero.pack(fill=X)
        ttk.Label(hero, text="DEVELOPMENT POSITION", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(hero, text=stage, style="Hero.TLabel").pack(anchor="w", pady=(8, 3))
        ttk.Label(hero, text=f"Approved next step: {next_step}", style="HeroMuted.TLabel", wraplength=780, justify="left").pack(anchor="w")
        actions = ttk.Frame(hero, style="CardAlt.TFrame")
        actions.pack(fill=X, pady=(18, 0))
        for caption, command, primary in (
            ("ПРОВЕРИТЬ ВСЁ", self._verify, True),
            ("ВСПОМНИТЬ ВСЁ", self._full_recall, False),
            ("ЗАПИСАТЬ ИСТОРИЮ", self._checkpoint_preview_flow, False),
            ("ПРОДОЛЖИТЬ РАЗРАБОТКУ", self._continue, False),
        ):
            ttk.Button(actions, text=caption, style="Primary.TButton" if primary else "Secondary.TButton", command=command).pack(side=LEFT, padx=(0, 8))
        ttk.Button(actions, text="TASK RECALL", style="Secondary.TButton", command=self._task_recall).pack(side=LEFT)
        for title, value in (
            ("GIT", f"{git.get('branch')} @ {git.get('head')}"),
            ("LOCAL VERIFICATION", f"{self.report.verification_id if self.report else 'NONE'} · {self.report.overall_state.value if self.report else 'NOT_CHECKED'}"),
            ("LATEST CHECKPOINT", checkpoint.checkpoint_id if checkpoint else "NONE"),
            ("LATEST PROMPT", f"{prompt.prompt_id} · {prompt.prompt_type.value}" if prompt else "NONE"),
            ("RECENT EVIDENCE", f"{(evidence.details.get('evidence_zip_count') if evidence else 0)} records · latest {(evidence.details.get('latest_evidence_timestamp') if evidence else 'UNKNOWN')}"),
        ):
            self._card(self.content, title, value).pack(fill=X, pady=4)

    def _page_roadmap(self) -> None:
        checkpoint = self.memory.latest_checkpoint()
        self._card(self.content, "GRAPHICAL LIVE ROADMAP", "PHASE 3 · NOT YET IMPLEMENTED\n\n" f"Current stage: {checkpoint.development_stage if checkpoint else 'NOT RECORDED'}\n" f"Approved next step: {checkpoint.approved_next_step if checkpoint and checkpoint.approved_next_step else 'USER CONFIRMATION REQUIRED'}\n\nPhase 3 will visualize Guard graph, checkpoints, Git, Evidence and proof-state transitions.").pack(fill=X)

    def _tree(self, columns: tuple[str, ...], headings: tuple[str, ...], height: int = 8) -> ttk.Treeview:
        tree = ttk.Treeview(self.content, columns=columns, show="headings", height=height)
        for column, heading in zip(columns, headings, strict=True):
            tree.heading(column, text=heading)
            tree.column(column, width=150, anchor="w")
        tree.pack(fill=X)
        return tree

    def _page_history(self) -> None:
        ttk.Label(self.content, text="DEVELOPMENT CHECKPOINTS", style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        self.checkpoint_tree = self._tree(
            ("time", "id", "head", "guard", "stage", "next", "proof"),
            ("TIME", "CHECKPOINT", "HEAD", "GUARD", "STAGE", "NEXT STEP", "PROOF"),
        )
        for item in self.memory.checkpoints.list_records(newest_first=True):
            proof = (
                f"FIELD {len(item.field_proven)} · "
                f"PROBE/AUTO {len(item.probe_or_automated_proven)} · "
                f"UNVALIDATED {len(item.unvalidated_work)}"
            )
            self.checkpoint_tree.insert(
                "",
                END,
                iid=item.checkpoint_id,
                values=(
                    item.created_at,
                    item.checkpoint_id,
                    item.head_sha[:7],
                    item.guard_report_id,
                    item.development_stage,
                    item.approved_next_step or "NOT RECORDED",
                    proof,
                ),
            )
        buttons = ttk.Frame(self.content, style="Orion.TFrame")
        buttons.pack(fill=X, pady=(8, 20))
        for caption, command in (("OPEN", self._open_checkpoint), ("COMPARE WITH CURRENT", self._compare_current), ("COMPARE WITH ANOTHER", self._compare_another), ("GENERATE PROMPT", self._checkpoint_prompt), ("COPY PROMPT", self._copy_checkpoint_prompt)):
            ttk.Button(buttons, text=caption, style="Secondary.TButton", command=command).pack(side=LEFT, padx=(0, 8))
        ttk.Label(self.content, text="PROMPT HISTORY", style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        self.prompt_tree = self._tree(("time", "type", "id", "head", "guard", "checkpoint", "task"), ("TIME", "TYPE", "PROMPT", "HEAD", "GUARD", "CHECKPOINT", "TASK / CAPABILITIES"))
        for item in self.memory.prompts.list_records(newest_first=True):
            self.prompt_tree.insert("", END, iid=item.prompt_id, values=(item.created_at, item.prompt_type.value, item.prompt_id, item.head_sha[:7], item.guard_report_id, item.checkpoint_id or "—", item.task or ", ".join(item.capabilities)))
        prompt_buttons = ttk.Frame(self.content, style="Orion.TFrame")
        prompt_buttons.pack(fill=X, pady=8)
        for caption, command in (("OPEN", self._open_prompt), ("COPY", self._copy_prompt_history), ("REGENERATE FROM CURRENT STATE", self._regenerate_prompt)):
            ttk.Button(prompt_buttons, text=caption, style="Secondary.TButton", command=command).pack(side=LEFT, padx=(0, 8))

    def _page_guard(self) -> None:
        guard = self.memory.guard_report()
        history = guard.get("history_coverage") or {}
        previous = guard.get("previous_best") or {}
        text = f"Report: {guard.get('report_id')}\nGate: {guard.get('gate')}\nHistory coverage: {history.get('overall', 'UNKNOWN')}\nCapabilities: {', '.join(item.get('capability_id', '') for item in guard.get('affected_capabilities', []))}\n\nCurrent decisions: {', '.join(item.get('decision_id', '') for item in (guard.get('decisions') or {}).get('CURRENT', []))}\nSuperseded: {', '.join(item.get('decision_id', '') for item in (guard.get('decisions') or {}).get('SUPERSEDED', [])) or 'NONE'}\nRejected: {', '.join(item.get('decision_id', '') for item in (guard.get('decisions') or {}).get('REJECTED', [])) or 'NONE'}\n\nConflicts: {len(guard.get('conflicts') or [])}\nOwnership drift: {len(guard.get('ownership_drift') or [])}\nPrevious Best implementation: {', '.join(previous.get('previous_best_whole_implementation', [])) or 'NONE'}\nPrevious Best mechanisms: {', '.join(previous.get('previous_best_mechanisms', [])) or 'NONE'}\n\nPrimary provenance remains addressable through the Guard report; raw private L0 bodies are not displayed."
        self._card(self.content, "ARCHITECTURE GUARD", text).pack(fill=X)
        ttk.Button(self.content, text="OPEN FULL BOUNDED REPORT", style="Secondary.TButton", command=lambda: self._show_text("Architecture Guard", json.dumps(guard, ensure_ascii=False, indent=2))).pack(anchor="w", pady=12)

    def _page_evidence(self) -> None:
        evidence = self.report.observation("evidence") if self.report else None
        details = evidence.details if evidence else {}
        self._card(self.content, "KNOWN EVIDENCE", f"Verification: {self.report.verification_id if self.report else 'NONE'}\nState: {evidence.state.value if evidence else 'NOT_CHECKED'}\nRecords: {details.get('evidence_zip_count', 0)}\nLatest timestamp: {details.get('latest_evidence_timestamp', 'UNKNOWN')}\nLatest build: {details.get('latest_evidence_build_sha', 'UNKNOWN')}").pack(fill=X)
        rows = [f"{item.get('node_type', 'SOURCE')}:{item.get('node_id', '')} → {item.get('source_item_id', '')}" for item in (self.memory.guard_report().get("primary_evidence") or [])[:40]]
        self._card(self.content, "GUARD EVIDENCE / PROVENANCE", "\n".join(rows) or "NONE").pack(fill=X, pady=8)

    def _page_system(self) -> None:
        ttk.Button(self.content, text="ПРОВЕРИТЬ ВСЁ", style="Primary.TButton", command=self._verify).pack(anchor="w", pady=(0, 12))
        by_subject = {row["subject"]: row for row in presentation_rows(self.report)} if self.report else {}
        for subject, title in SUBJECT_TITLES.items():
            row = by_subject.get(subject, {"state": "NOT_CHECKED", "summary": "Not checked", "verified_at": "—"})
            card = ttk.Frame(self.content, style="Card.TFrame", padding=14)
            card.pack(fill=X, pady=4)
            ttk.Label(card, text=f"[{row['state']}] {title}", style="CardTitle.TLabel").pack(side=LEFT)
            ttk.Label(card, text=row["summary"], style="CardText.TLabel").pack(side=LEFT, fill=X, expand=True, padx=14)
            ttk.Label(card, text=row["verified_at"], style="CardText.TLabel").pack(side=LEFT)
            ttk.Button(card, text="DETAILS", style="Secondary.TButton", command=lambda value=subject: self._show_system_details(value)).pack(side=RIGHT, padx=(10, 0))

    def _verify(self) -> None:
        def worker() -> None:
            try:
                self._result_queue.put(self.engine.verify_everything())
            except BaseException as exc:
                self._result_queue.put(exc)
        threading.Thread(target=worker, name="orion-development-verifier", daemon=True).start()
        self.root.after(100, self._poll_result)

    def _poll_result(self) -> None:
        try:
            result = self._result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_result)
            return
        if isinstance(result, BaseException):
            messagebox.showerror("Verification failed", f"{type(result).__name__}: {result}", parent=self.root)
            return
        self.report = result
        self.show_page(self.current_page)

    def _full_recall(self) -> None:
        try:
            self._show_prompt(self.memory.generate_full_recall())
        except (OSError, ValueError) as error:
            messagebox.showerror("Recall failed", str(error), parent=self.root)

    def _task_recall(self) -> None:
        task = simpledialog.askstring("TASK RECALL", "Enter the ORION task or capability:", parent=self.root)
        if task is None:
            return
        try:
            self._show_prompt(self.memory.generate_task_recall(task))
        except AmbiguousTaskRecall as error:
            messagebox.showwarning("Task clarification required", str(error), parent=self.root)
        except (OSError, ValueError) as error:
            messagebox.showerror("Task Recall failed", str(error), parent=self.root)

    def _continue(self) -> None:
        try:
            self._show_prompt(self.memory.generate_continue())
        except (OSError, ValueError) as error:
            messagebox.showwarning("Cannot continue", str(error), parent=self.root)

    def _checkpoint_preview_flow(self) -> None:
        stage = simpledialog.askstring("Current Development Stage", "Enter the explicitly confirmed development stage:", parent=self.root)
        if stage is None:
            return
        next_step = simpledialog.askstring("Approved Next Step", "Enter the explicitly approved next step. Leave empty only to record that no next step is approved:", parent=self.root)
        if next_step is None:
            return
        try:
            candidate = self.memory.build_checkpoint_candidate(development_stage=stage, approved_next_step=next_step or None, known_problems=["Direct ChatGPT/Codex send has no approved Console integration contract"], risks=[] if next_step else ["Approved Next Step is not recorded; Continue remains blocked"])
        except ValueError as error:
            messagebox.showwarning("Checkpoint input required", str(error), parent=self.root)
            return
        self._show_checkpoint_preview(candidate)

    def _show_checkpoint_preview(self, candidate: DevelopmentCheckpoint) -> None:
        window = self._window("CHECKPOINT PREVIEW · NOT SAVED", "900x680")
        text = self._text_widget(window)
        text.insert("1.0", json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False, indent=2))
        text.configure(state="disabled")
        footer = ttk.Frame(window, style="Orion.TFrame", padding=12)
        footer.pack(fill=X)
        def save() -> None:
            if not messagebox.askyesno("Save immutable checkpoint", f"Create {candidate.checkpoint_id}? It cannot be overwritten.", parent=window):
                return
            try:
                self.memory.save_checkpoint(candidate)
            except (OSError, ValueError) as error:
                messagebox.showerror("Checkpoint save failed", str(error), parent=window)
                return
            window.destroy()
            self.show_page("history")
        ttk.Button(footer, text="SAVE CHECKPOINT", style="Primary.TButton", command=save).pack(side=RIGHT)
        ttk.Button(footer, text="CANCEL", style="Secondary.TButton", command=window.destroy).pack(side=RIGHT, padx=8)

    def _selected_checkpoint(self) -> DevelopmentCheckpoint | None:
        selection = self.checkpoint_tree.selection() if self.checkpoint_tree else ()
        if not selection:
            messagebox.showwarning("Checkpoint required", "Select a checkpoint first.", parent=self.root)
            return None
        return self.memory.checkpoints.load(selection[0])

    def _selected_prompt(self) -> PromptRecord | None:
        selection = self.prompt_tree.selection() if self.prompt_tree else ()
        if not selection:
            messagebox.showwarning("Prompt required", "Select a prompt first.", parent=self.root)
            return None
        return self.memory.prompts.load(selection[0])

    def _open_checkpoint(self) -> None:
        item = self._selected_checkpoint()
        if item:
            self._show_text(item.checkpoint_id, json.dumps(item.model_dump(mode="json"), ensure_ascii=False, indent=2))

    def _compare_current(self) -> None:
        item = self._selected_checkpoint()
        if item:
            current = self.memory.build_checkpoint_candidate(development_stage=item.development_stage, approved_next_step=item.approved_next_step)
            self._show_text("Checkpoint comparison", render_comparison(compare_checkpoints(item, current)))

    def _compare_another(self) -> None:
        left = self._selected_checkpoint()
        if left is None:
            return
        identifier = simpledialog.askstring("Compare checkpoints", "Enter the other checkpoint ID:", parent=self.root)
        if not identifier:
            return
        try:
            right = self.memory.checkpoints.load(identifier)
        except ValueError as error:
            messagebox.showerror("Checkpoint not found", str(error), parent=self.root)
            return
        self._show_text("Checkpoint comparison", render_comparison(compare_checkpoints(left, right)))

    def _checkpoint_prompt(self) -> None:
        item = self._selected_checkpoint()
        if item:
            self._show_prompt(self.memory.checkpoint_recovery_prompt(item))

    def _copy_checkpoint_prompt(self) -> None:
        item = self._selected_checkpoint()
        if item:
            record = self.memory.checkpoint_recovery_prompt(item)
            self._copy(record.content)
            messagebox.showinfo("Prompt copied", record.prompt_id, parent=self.root)
            self.show_page("history")

    def _open_prompt(self) -> None:
        item = self._selected_prompt()
        if item:
            self._show_prompt(item)

    def _copy_prompt_history(self) -> None:
        item = self._selected_prompt()
        if item:
            self._copy(item.content)
            messagebox.showinfo("Prompt copied", item.prompt_id, parent=self.root)

    def _regenerate_prompt(self) -> None:
        item = self._selected_prompt()
        if item:
            try:
                self._show_prompt(self.memory.regenerate_prompt(item))
            except (OSError, ValueError) as error:
                messagebox.showerror("Regeneration failed", str(error), parent=self.root)

    def _show_system_details(self, subject: str) -> None:
        observation = self.report.observation(subject) if self.report else None
        if observation:
            self._show_text(SUBJECT_TITLES[subject], json.dumps(observation.model_dump(mode="json"), ensure_ascii=False, indent=2))

    def _window(self, title: str, geometry: str) -> Toplevel:
        window = Toplevel(self.root)
        window.title(f"ORION Development Console · {title}")
        window.geometry(geometry)
        window.configure(background=PALETTE["background"])
        return window

    def _text_widget(self, window: Toplevel) -> tk.Text:
        text = tk.Text(window, wrap="word", bg=PALETTE["status"], fg="#c6d2dc", insertbackground=PALETTE["foreground"], relief="flat", font=("Consolas", 10))
        text.pack(fill=BOTH, expand=True, padx=12, pady=12)
        return text

    def _show_text(self, title: str, content: str) -> None:
        window = self._window(title, "900x680")
        text = self._text_widget(window)
        text.insert("1.0", content)
        text.configure(state="disabled")

    def _show_prompt(self, record: PromptRecord) -> None:
        window = self._window(f"{record.prompt_type.value} · {record.prompt_id}", "960x720")
        text = self._text_widget(window)
        text.insert("1.0", record.content)
        text.configure(state="disabled")
        footer = ttk.Frame(window, style="Orion.TFrame", padding=12)
        footer.pack(fill=X)
        ttk.Button(footer, text="COPY PROMPT", style="Primary.TButton", command=lambda: self._copy(record.content)).pack(side=LEFT)
        ttk.Button(footer, text="SAVE PROMPT", style="Secondary.TButton", command=lambda: self._export_prompt(record)).pack(side=LEFT, padx=8)
        ttk.Button(footer, text="SEND · UNSUPPORTED", style="Secondary.TButton", state="disabled").pack(side=LEFT)

    def _copy(self, content: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.root.update_idletasks()

    def _export_prompt(self, record: PromptRecord) -> None:
        target = filedialog.asksaveasfilename(parent=self.root, title="Save private prompt copy", initialfile=f"{record.prompt_id}.txt", defaultextension=".txt", filetypes=(("Text", "*.txt"), ("All files", "*.*")))
        if target:
            Path(target).write_text(record.content, encoding="utf-8", newline="\n")


def run_ui(repository_root: Path) -> None:
    context = VerificationContext.defaults(repository_root)
    root = Tk()
    engine = VerificationEngine(context)
    DevelopmentConsoleApp(root, engine)
    root.mainloop()
