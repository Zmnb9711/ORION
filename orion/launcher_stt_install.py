from __future__ import annotations

import threading
import tkinter as tk
from tkinter import LEFT, X, messagebox, ttk

from orion import whisper_cpp_stt as stt


class LauncherSttInstallMixin:
    """Explicit, user-controlled Whisper STT installation for the Windows Launcher."""

    def _page_test(self) -> None:
        self._render_stt_install_card()
        super()._page_test()

    def _stt_status_text(self) -> str:
        if stt.runtime_ready():
            return f"READY — whisper.cpp {stt.WHISPER_CPP_VERSION} / Medium / CPU-only"
        model_part = stt.model_part_path()
        runtime_part = stt.runtime_archive_part_path()
        if model_part.is_file():
            return f"NOT INSTALLED — Medium download can resume from {model_part.stat().st_size / (1024 ** 2):.1f} MB"
        if runtime_part.is_file():
            return f"NOT INSTALLED — whisper.cpp download can resume from {runtime_part.stat().st_size / (1024 ** 2):.1f} MB"
        return f"NOT INSTALLED — whisper.cpp {stt.WHISPER_CPP_VERSION} / Medium / CPU-only"

    def _render_stt_install_card(self) -> None:
        card = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        card.pack(fill=X, pady=(0, 10))
        ttk.Label(card, text="WHISPER STT", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text="Speech recognition is installed separately and is never downloaded silently by LAUNCH DCS or START AUDIO TEST.",
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(4, 7))

        ready = stt.runtime_ready()
        status_var = tk.StringVar(value=self._stt_status_text())
        detail_var = tk.StringVar(value="")
        ttk.Label(card, textvariable=status_var, style="CardText.TLabel").pack(anchor="w")
        detail_label = ttk.Label(
            card,
            textvariable=detail_var,
            style="Muted.TLabel",
            wraplength=780,
            justify="left",
        )
        progress = ttk.Progressbar(card, orient="horizontal", mode="determinate", maximum=100)
        if not ready:
            detail_label.pack(anchor="w", pady=(2, 7))
            progress.pack(fill=X, pady=(2, 9))

        row = tk.Frame(card, bg="#111923")
        row.pack(fill=X)
        button = self._action_button(
            row,
            "DOWNLOAD & INSTALL STT",
            lambda: self._install_stt_async(status_var, detail_var, detail_label, progress, button),
            primary=True,
            enabled=not ready,
        )
        button.pack(side=LEFT)

    def _install_stt_async(self, status_var, detail_var, detail_label, progress, button) -> None:  # noqa: ANN001
        if getattr(self, "_stt_install_running", False):
            return
        self._stt_install_running = True
        button.configure(state="disabled")
        status_var.set("DOWNLOADING / INSTALLING")
        if not detail_label.winfo_manager():
            detail_label.pack(anchor="w", pady=(2, 7))
        if not progress.winfo_manager():
            progress.pack(fill=X, pady=(2, 9))

        def ui_progress(stage: str, done: int, total: int | None) -> None:
            def apply() -> None:
                try:
                    if total and total > 0:
                        percent = min(100.0, done * 100.0 / total)
                        progress.configure(value=percent)
                        detail_var.set(
                            f"{stage.upper()} — {done / (1024 ** 2):.1f} / {total / (1024 ** 2):.1f} MB ({percent:.1f}%)"
                        )
                    else:
                        detail_var.set(f"{stage.upper()} — {done / (1024 ** 2):.1f} MB")
                except tk.TclError:
                    pass

            self.root.after(0, apply)

        def worker() -> None:
            try:
                stt.ensure_runtime(progress=ui_progress)
            except Exception as exc:
                error = str(exc)

                def failed() -> None:
                    self._stt_install_running = False
                    try:
                        status_var.set("ERROR — installation incomplete; downloaded .part files were preserved")
                        detail_var.set(error)
                        button.configure(state="normal")
                        messagebox.showerror("ORION — Whisper STT", error, parent=self.root)
                    except tk.TclError:
                        pass

                self.root.after(0, failed)
                return

            def completed() -> None:
                self._stt_install_running = False
                try:
                    status_var.set(f"READY — whisper.cpp {stt.WHISPER_CPP_VERSION} / Medium / CPU-only")
                    detail_var.set("")
                    detail_label.pack_forget()
                    progress.pack_forget()
                    button.configure(state="disabled")
                except tk.TclError:
                    pass

            self.root.after(0, completed)

        threading.Thread(target=worker, name="orion-stt-install", daemon=True).start()
