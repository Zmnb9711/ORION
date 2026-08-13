from __future__ import annotations

from pathlib import Path
from tkinter import Tk

from orion.core_process import CoreProcessManager
from orion.desktop_launcher import _install_tk_exception_boundary
from orion.desktop_launcher_conversation import ConversationalAudioRuntimeLauncher
from orion.launcher_field_ui_fix import LauncherFieldUiFixMixin


class FieldFixedConversationalAudioLauncher(LauncherFieldUiFixMixin, ConversationalAudioRuntimeLauncher):
    """Canonical Launcher with field-tested UI stability/readability fixes."""


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
