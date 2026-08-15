from __future__ import annotations

from pathlib import Path
from tkinter import Tk

from orion.core_process import CoreProcessManager
from orion.desktop_launcher import _install_tk_exception_boundary
from orion.desktop_launcher_audio import AudioAwareRuntimeLauncher
from orion.launcher_conversation_test import LauncherConversationTestMixin


class ConversationalAudioRuntimeLauncher(LauncherConversationTestMixin, AudioAwareRuntimeLauncher):
    """Canonical Launcher plus the conversational Audio Test."""


def run_conversational_audio_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    core.start()
    try:
        root = Tk()
        _install_tk_exception_boundary(root, runtime_dir)
        ConversationalAudioRuntimeLauncher(root, runtime_dir=runtime_dir, core=core)  # type: ignore[arg-type]
        root.mainloop()
    finally:
        core.stop()
    return 0
