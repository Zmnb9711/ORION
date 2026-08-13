from __future__ import annotations

from pathlib import Path
from tkinter import Tk

from orion.core_process import CoreProcessManager
from orion.desktop_launcher import (
    LauncherConfig,
    LauncherConfigStore,
    OrionDesktopLauncher,
    RuntimeSynchronizedWindowsOrionProductLauncher,
    _install_tk_exception_boundary,
)
from orion.launcher_audio_sections import LauncherAudioSectionsMixin


class AudioAwareRuntimeLauncher(LauncherAudioSectionsMixin, RuntimeSynchronizedWindowsOrionProductLauncher):
    """Canonical Windows Launcher with Modules, Test and Settings/Audio sections."""


def run_audio_desktop_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    core.start()
    try:
        root = Tk()
        _install_tk_exception_boundary(root, runtime_dir)
        AudioAwareRuntimeLauncher(root, runtime_dir=runtime_dir, core=core)  # type: ignore[arg-type]
        root.mainloop()
    finally:
        core.stop()
    return 0


__all__ = [
    "AudioAwareRuntimeLauncher",
    "CoreProcessManager",
    "LauncherConfig",
    "LauncherConfigStore",
    "OrionDesktopLauncher",
    "run_audio_desktop_launcher",
]
