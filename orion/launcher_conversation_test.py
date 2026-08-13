from __future__ import annotations

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

    def _run_conversational_audio_test(self) -> None:
        try:
            result = self._core_json("/v1/windows-audio/test/conversation", method="POST")
        except RuntimeError as exc:
            messagebox.showerror("ORION Audio Test", str(exc), parent=self.root)
            return
        stages = result.get("stages", {})
        ordered = (
            ("core_connected", "Core connected"),
            ("input_resolved", "Input resolved"),
            ("audio_captured", "Audio captured"),
            ("phrase_recognized", "Phrase recognized"),
            ("output_resolved", "Output resolved"),
            ("response_played", "Response played"),
        )
        details = "\n".join(f"{'PASS' if stages.get(key) else 'FAIL'} — {label}" for key, label in ordered)
        recognized = str(result.get("recognized_text", "")).strip()
        if recognized:
            details += f"\n\nRecognized: {recognized}"
        text = f"{result.get('message', 'Audio test completed')}\n\n{details}"
        if result.get("ok"):
            messagebox.showinfo("ORION Audio Test", text, parent=self.root)
        else:
            messagebox.showwarning("ORION Audio Test", text, parent=self.root)
