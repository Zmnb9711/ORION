from __future__ import annotations

from pathlib import Path
from tkinter import Tk
from typing import Any

from orion.core_process import CoreProcessManager
from orion.desktop_launcher import _install_tk_exception_boundary
from orion.desktop_launcher_conversation import ConversationalAudioRuntimeLauncher
from orion.launcher_ui import LauncherUiMixin
from orion.launcher_uninstall import LauncherUninstallMixin


class OrionLauncher(
    LauncherUninstallMixin,
    LauncherUiMixin,
    ConversationalAudioRuntimeLauncher,
):
    """Single production ORION Launcher shell."""

    def close(self) -> None:
        """Use the Windows tray policy without giving UI code ownership of Core."""
        super().close()

    def exit_application(self) -> None:
        """Exit the Launcher process while leaving independent Core alive."""
        if getattr(self, "_really_exiting", False):
            return
        self._really_exiting = True
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.stop()
        self.root.destroy()

    def _apply_stt_status(self, payload: dict[str, Any]) -> None:
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


def run_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    core.start()
    try:
        root = Tk()
        _install_tk_exception_boundary(root, runtime_dir)
        OrionLauncher(root, runtime_dir=runtime_dir, core=core)  # type: ignore[arg-type]
        root.mainloop()
    finally:
        core.detach()
    return 0
