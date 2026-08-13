from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import perf_counter
from tkinter import X, messagebox
from tkinter import ttk


class LauncherConversationTestMixin:
    """Add the approved conversational Voice↔Core diagnostic to Test."""

    def _page_test(self) -> None:
        super()._page_test()
        card = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        card.pack(fill=X, pady=(12, 0))
        ttk.Label(card, text="CONVERSATIONAL AUDIO TEST", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text='Press START, then say: “Привет, как дела?” ORION should answer: “Дела отлично. Связь установлена.”',
            style="CardText.TLabel",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(6, 10))
        button = ttk.Button(card, text="START CONVERSATIONAL AUDIO TEST", style="Primary.TButton", command=self._run_conversational_audio_test)
        button.pack(anchor="w")
        if not self.core.healthy():
            button.configure(state="disabled")

    def _new_test_log(self, test_name: str) -> Path:
        log_dir = self.runtime_dir / "test-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = log_dir / f"orion-test-{timestamp}.log"
        self._append_test_log(path, f"START test={test_name}")
        self._append_test_log(path, f"core_base_url={self.core.base_url}")
        return path

    @staticmethod
    def _append_test_log(path: Path, message: str) -> None:
        stamp = datetime.now().isoformat(timespec="milliseconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")

    def _run_conversational_audio_test(self) -> None:
        log_path = self._new_test_log("conversation")
        started = perf_counter()
        self._append_test_log(log_path, "REQUEST method=POST path=/v1/windows-audio/test/conversation")
        try:
            result = self._core_json("/v1/windows-audio/test/conversation", method="POST")
        except RuntimeError as exc:
            elapsed_ms = (perf_counter() - started) * 1000.0
            self._append_test_log(log_path, f"ERROR elapsed_ms={elapsed_ms:.1f} exception={type(exc).__name__}: {exc}")
            self._append_test_log(log_path, "END status=FAIL")
            messagebox.showerror("ORION Audio Test", f"{exc}\n\nTest log:\n{log_path}", parent=self.root)
            return

        elapsed_ms = (perf_counter() - started) * 1000.0
        self._append_test_log(log_path, f"RESPONSE elapsed_ms={elapsed_ms:.1f} ok={bool(result.get('ok'))}")
        stages = result.get("stages", {})
        for key, value in stages.items():
            self._append_test_log(log_path, f"STAGE {key}={bool(value)}")
        recognized = str(result.get("recognized_text", "")).strip()
        if recognized:
            self._append_test_log(log_path, f"RECOGNIZED text={recognized!r}")
        self._append_test_log(log_path, f"MESSAGE {result.get('message', 'Audio test completed')}")
        self._append_test_log(log_path, f"END status={'PASS' if result.get('ok') else 'FAIL'}")

        ordered = (
            ("core_connected", "Core connected"),
            ("input_resolved", "Input resolved"),
            ("audio_captured", "Audio captured"),
            ("phrase_recognized", "Phrase recognized"),
            ("output_resolved", "Output resolved"),
            ("response_played", "Response played"),
        )
        details = "\n".join(f"{'PASS' if stages.get(key) else 'FAIL'} — {label}" for key, label in ordered)
        if recognized:
            details += f"\n\nRecognized: {recognized}"
        text = f"{result.get('message', 'Audio test completed')}\n\n{details}\n\nTest log:\n{log_path}"
        if result.get("ok"):
            messagebox.showinfo("ORION Audio Test", text, parent=self.root)
        else:
            messagebox.showwarning("ORION Audio Test", text, parent=self.root)
