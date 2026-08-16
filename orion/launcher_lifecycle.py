from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from tkinter import messagebox
from typing import Any

from orion.recovery_launch import start_dcs_for_recovery


class LauncherVoiceLifecycleMixin:
    """Canonical product lifecycle for Launcher -> Voice -> Core.

    Window close remains a tray operation in the Windows shell. Explicit Exit
    shuts Voice down first, then the owned Core, then destroys Launcher.
    """

    def _voice_request(self, path: str, *, timeout: float = 30.0) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.core.base_url}{path}", method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Voice lifecycle API unavailable: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Voice lifecycle API returned invalid JSON")
        return payload

    def _ensure_voice_ready(self) -> dict[str, Any]:
        status = self._voice_request("/v1/windows-audio/voice/ensure", timeout=120.0)
        if status.get("state") != "ready" or not status.get("worker_alive") or not status.get("whisper_ready"):
            raise RuntimeError(str(status.get("message") or "Voice/Whisper failed to become READY"))
        return status

    def _conversation_core_json(self) -> Any:
        self._ensure_voice_ready()
        result = super()._conversation_core_json()
        status = self._voice_request("/v1/windows-audio/voice/ensure", timeout=10.0)
        if status.get("state") != "ready" or not status.get("worker_alive") or not status.get("whisper_ready"):
            raise RuntimeError("Voice/Whisper did not remain READY after audio test")
        return result

    def _launch_dcs_async(self) -> None:
        def worker() -> None:
            try:
                self._ensure_voice_ready()
                result = start_dcs_for_recovery()
            except Exception as exc:
                error = str(exc)
                self.root.after(0, lambda: messagebox.showerror("ORION", error, parent=self.root))
                return
            self.root.after(0, lambda: messagebox.showinfo("ORION", result.message, parent=self.root))

        threading.Thread(target=worker, name="orion-launch-dcs", daemon=True).start()

    def exit_application(self) -> None:
        if getattr(self, "_really_exiting", False):
            return
        self._really_exiting = True
        try:
            self._tray.stop()
        except Exception:
            pass

        try:
            self._voice_request("/v1/windows-audio/voice/shutdown", timeout=7.0)
        except Exception:
            # Core shutdown below is the final containment boundary. A Voice
            # worker that refuses graceful shutdown must not keep Launcher open.
            pass

        shutdown = getattr(self.core, "shutdown", None)
        if callable(shutdown):
            shutdown()
        else:
            self.core.stop()
        self.root.destroy()
