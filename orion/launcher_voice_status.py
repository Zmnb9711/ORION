from __future__ import annotations

import json
from tkinter import LEFT, X, StringVar, ttk


class LauncherVoiceStatusMixin:
    """Render and control the independent Whisper worker without Core audio capture."""

    VOICE_STATUS_POLL_MS = 500

    def _voice_state_snapshot(self) -> dict[str, str]:
        path = self.runtime_dir / "voice" / "state.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"state": "STOPPED", "heard": "", "reply": "", "error": ""}
        if not isinstance(payload, dict):
            return {"state": "ERROR", "heard": "", "reply": "", "error": "Invalid Voice state payload"}
        return {
            "state": str(payload.get("state", "UNKNOWN")),
            "heard": str(payload.get("heard", "")),
            "reply": str(payload.get("reply", "")),
            "error": str(payload.get("error", "")),
        }

    def _voice_start(self) -> None:
        voice = getattr(self, "voice", None)
        if voice is None:
            return
        try:
            voice.start()
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            voice._write_state("ERROR", error=f"{type(exc).__name__}: {exc}")

    def _voice_stop(self) -> None:
        voice = getattr(self, "voice", None)
        if voice is not None:
            voice.stop()

    def _voice_restart(self) -> None:
        self._voice_stop()
        self._voice_start()

    def _page_test(self) -> None:
        self._voice_status_card()
        super()._page_test()

    def _voice_status_card(self) -> None:
        card = ttk.Frame(self.content, style="CardAlt.TFrame", padding=18)
        card.pack(fill=X, pady=(0, 12))
        ttk.Label(card, text="VOICE v0.1 — WHISPER → TEXT → CORE → TTS", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text='Live Voice is independent from Core audio capture. Say “Привет, как дела?”; expected spoken reply: “Всё хорошо. Связь установлена.”',
            style="HeroMuted.TLabel",
            wraplength=800,
            justify="left",
        ).pack(anchor="w", pady=(5, 10))

        state_var = StringVar(value="VOICE: STARTING")
        heard_var = StringVar(value="HEARD: —")
        reply_var = StringVar(value="CORE REPLY: —")
        error_var = StringVar(value="")
        ttk.Label(card, textvariable=state_var, style="CardAltTitle.TLabel").pack(anchor="w", pady=(2, 3))
        ttk.Label(card, textvariable=heard_var, style="CardText.TLabel", wraplength=790, justify="left").pack(anchor="w")
        ttk.Label(card, textvariable=reply_var, style="CardText.TLabel", wraplength=790, justify="left").pack(anchor="w", pady=(2, 0))
        ttk.Label(card, textvariable=error_var, style="CardText.TLabel", wraplength=790, justify="left").pack(anchor="w", pady=(2, 6))

        controls = ttk.Frame(card, style="CardAlt.TFrame")
        controls.pack(fill=X, pady=(5, 0))
        self._action_button(controls, "START / RESTART VOICE", self._voice_restart, primary=True).pack(side=LEFT, padx=(0, 8))
        self._action_button(controls, "STOP VOICE", self._voice_stop).pack(side=LEFT)

        def refresh() -> None:
            try:
                if not card.winfo_exists():
                    return
            except Exception:
                return
            snapshot = self._voice_state_snapshot()
            state_var.set(f"VOICE: {snapshot['state']}")
            heard_var.set(f"HEARD: {snapshot['heard'] or '—'}")
            reply_var.set(f"CORE REPLY: {snapshot['reply'] or '—'}")
            error_var.set(f"ERROR: {snapshot['error']}" if snapshot["error"] else "")
            self.root.after(self.VOICE_STATUS_POLL_MS, refresh)

        refresh()
