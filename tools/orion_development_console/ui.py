from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, Tk, Toplevel, messagebox, ttk

from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.engine import VerificationEngine
from tools.orion_development_console.models import VerificationReport
from tools.orion_development_console.presentation import SUBJECT_TITLES, presentation_rows


class DevelopmentConsoleApp:
    """Separate dev-only Tk UI. It never starts the production ORION runtime."""

    def __init__(self, root: Tk, engine: VerificationEngine) -> None:
        self.root = root
        self.engine = engine
        self.report: VerificationReport | None = engine.cached_report()
        self._result_queue: queue.SimpleQueue[VerificationReport | BaseException] = queue.SimpleQueue()
        self._rows: dict[str, tuple[ttk.Label, ttk.Label, ttk.Label, ttk.Button]] = {}
        self.guard_var = ""
        self.local_var = ""
        self.root.title("ORION Development Console")
        self.root.geometry("1040x720")
        self.root.minsize(860, 600)
        self._build()
        self._render()

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=22)
        outer.pack(fill=BOTH, expand=True)
        ttk.Label(outer, text="ORION DEVELOPMENT CONSOLE", font=("Segoe UI Semibold", 22)).pack(anchor="w")
        self.guard_label = ttk.Label(outer, font=("Segoe UI Semibold", 12))
        self.guard_label.pack(anchor="w", pady=(12, 3))
        self.local_label = ttk.Label(outer, font=("Segoe UI Semibold", 12))
        self.local_label.pack(anchor="w", pady=(0, 14))
        self.verify_button = ttk.Button(outer, text="ПРОВЕРИТЬ ВСЁ", command=self._verify)
        self.verify_button.pack(anchor="w", pady=(0, 16))

        panel = ttk.Frame(outer)
        panel.pack(fill=BOTH, expand=True)
        for index, title in enumerate(SUBJECT_TITLES.values()):
            subject = tuple(SUBJECT_TITLES)[index]
            card = ttk.LabelFrame(panel, text=title, padding=12)
            card.pack(fill=X, pady=4)
            state = ttk.Label(card, text="NOT_CHECKED", width=14, font=("Segoe UI Semibold", 10))
            state.pack(side=LEFT)
            summary = ttk.Label(card, text="Not checked", anchor="w")
            summary.pack(side=LEFT, fill=X, expand=True, padx=12)
            verified = ttk.Label(card, text="—", width=28)
            verified.pack(side=LEFT)
            details = ttk.Button(card, text="Подробнее", command=lambda value=subject: self._show_details(value))
            details.pack(side=RIGHT, padx=(10, 0))
            self._rows[subject] = (state, summary, verified, details)

    def _render(self) -> None:
        if self.report is None:
            self.guard_label.configure(text=f"ARCHITECTURE GUARD: ON — {self.engine.context.architecture_report_id}")
            self.local_label.configure(text="LOCAL ENVIRONMENT: NOT_CHECKED")
            return
        self.guard_label.configure(
            text=f"ARCHITECTURE GUARD: ON — {self.report.architecture_guard_report_id}"
        )
        self.local_label.configure(text=f"LOCAL ENVIRONMENT: {self.report.overall_state.value}")
        for row in presentation_rows(self.report):
            state, summary, verified, details = self._rows[row["subject"]]
            state.configure(text=row["state"])
            summary.configure(text=row["summary"])
            verified.configure(text=row["verified_at"])
            details.configure(state="normal")

    def _verify(self) -> None:
        self.verify_button.configure(state="disabled")
        self.local_label.configure(text="LOCAL ENVIRONMENT: VERIFYING")

        def worker() -> None:
            try:
                self._result_queue.put(self.engine.verify_everything())
            except BaseException as exc:  # UI boundary must surface collector failures.
                self._result_queue.put(exc)

        threading.Thread(target=worker, name="orion-development-verifier", daemon=True).start()
        self.root.after(100, self._poll_result)

    def _poll_result(self) -> None:
        try:
            result = self._result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_result)
            return
        self.verify_button.configure(state="normal")
        if isinstance(result, BaseException):
            self.local_label.configure(text="LOCAL ENVIRONMENT: ERROR")
            messagebox.showerror("Verification failed", f"{type(result).__name__}: {result}")
            return
        self.report = result
        self._render()

    def _show_details(self, subject: str) -> None:
        observation = self.report.observation(subject) if self.report else None
        if observation is None:
            return
        window = Toplevel(self.root)
        window.title(f"{SUBJECT_TITLES[subject]} — verification details")
        window.geometry("840x560")
        text = __import__("tkinter").Text(window, wrap="word", font=("Consolas", 10))
        text.pack(fill=BOTH, expand=True, padx=12, pady=12)
        text.insert("1.0", json.dumps(observation.model_dump(mode="json"), ensure_ascii=False, indent=2))
        text.configure(state="disabled")


def run_ui(repository_root: Path) -> None:
    context = VerificationContext.defaults(repository_root)
    root = Tk()
    DevelopmentConsoleApp(root, VerificationEngine(context))
    root.mainloop()
