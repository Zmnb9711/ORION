from __future__ import annotations

from pathlib import Path
from tkinter import Tk

from orion.core_process import CoreProcessManager
from orion.desktop_launcher import _install_tk_exception_boundary
from orion.desktop_launcher_conversation import ConversationalAudioRuntimeLauncher
from orion.launcher_field_ui_fix import LauncherFieldUiFixMixin
from orion.launcher_voice_status import LauncherVoiceStatusMixin
from orion.voice_process import VoiceProcessManager


class FieldFixedConversationalAudioLauncher(
    LauncherVoiceStatusMixin,
    LauncherFieldUiFixMixin,
    ConversationalAudioRuntimeLauncher,
):
    """Canonical Launcher with field-tested UI stability/readability fixes."""

    def exit_application(self) -> None:
        """Fully exit ORION in the required child-before-parent order.

        Closing the window is handled by ``WindowsOrionDesktopLauncher.close``
        and only withdraws it to the tray.  This method is reserved for the
        explicit tray Exit action and therefore owns the full runtime shutdown:
        Voice/Whisper first, Core second, Launcher last.
        """
        if getattr(self, "_really_exiting", False):
            return
        self._really_exiting = True
        self._tray.stop()
        voice = getattr(self, "voice", None)
        if voice is not None:
            voice.stop()
        self.core.shutdown()
        self.root.destroy()


def run_field_fixed_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    voice = VoiceProcessManager(runtime_dir, core.base_url)
    core.start()
    try:
        # Voice owns the microphone/STT process. Core receives recognized text only.
        # Failure to provision/start Voice must not make the Launcher/Core unusable;
        # the dedicated Test surface remains available for diagnosis/repair.
        try:
            voice.start()
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            voice._write_state("ERROR", error=f"{type(exc).__name__}: {exc}")
        root = Tk()
        _install_tk_exception_boundary(root, runtime_dir)
        launcher = FieldFixedConversationalAudioLauncher(root, runtime_dir=runtime_dir, core=core)  # type: ignore[arg-type]
        launcher.voice = voice
        root.mainloop()
    finally:
        # Also contain abnormal UI termination. These operations are idempotent;
        # a normal tray Exit will already have completed them in the same order.
        voice.stop()
        core.shutdown()
    return 0
