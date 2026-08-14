from __future__ import annotations

from pathlib import Path
from tkinter import Tk
from typing import Any

from orion.core_process import CoreProcessManager
from orion.desktop_launcher import _install_tk_exception_boundary
from orion.desktop_launcher_conversation import ConversationalAudioRuntimeLauncher
from orion.launcher_field_ui_fix import LauncherFieldUiFixMixin


class FieldFixedConversationalAudioLauncher(LauncherFieldUiFixMixin, ConversationalAudioRuntimeLauncher):
    """Canonical Launcher with field-tested UI stability/readability fixes."""

    def _apply_stt_status(self, payload: dict[str, Any]) -> None:
        """Apply STT state and keep the field-tested button styling in sync.

        The generic conversational mixin correctly flips the Tk button state,
        but field UI buttons are created with explicit disabled background and
        cursor values.  Restore the active visual state once Whisper is ready so
        the control both behaves and looks enabled to the user.
        """
        super()._apply_stt_status(payload)
        conversation = getattr(self, "_conversation_button", None)
        if conversation is None:
            return

        ready = bool(payload.get("ready"))
        if ready:
            conversation.configure(
                state="normal",
                bg="#4ac6d7",
                fg="#031014",
                activebackground="#6bd7e5",
                activeforeground="#031014",
                cursor="hand2",
            )
        else:
            conversation.configure(
                state="disabled",
                bg="#17222b",
                disabledforeground="#7b8994",
                cursor="arrow",
            )


def run_field_fixed_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    core.start()
    try:
        root = Tk()
        _install_tk_exception_boundary(root, runtime_dir)
        FieldFixedConversationalAudioLauncher(root, runtime_dir=runtime_dir, core=core)  # type: ignore[arg-type]
        root.mainloop()
    finally:
        core.stop()
    return 0
