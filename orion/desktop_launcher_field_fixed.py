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
        voice.stop()
        core.stop()
    return 0
