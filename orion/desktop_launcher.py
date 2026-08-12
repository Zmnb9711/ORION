from __future__ import annotations

from pathlib import Path
from tkinter import Tk

# Compatibility surface kept for existing imports while production launch is
# moved onto a separate ORION Core process.
from orion.core_process import CoreProcessManager
from orion.desktop_app import LauncherConfig, LauncherConfigStore, OrionDesktopLauncher
from orion.desktop_product_launcher import WindowsOrionProductLauncher


def run_desktop_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    core.start()
    try:
        root = Tk()
        WindowsOrionProductLauncher(root, runtime_dir=runtime_dir, core=core)  # type: ignore[arg-type]
        root.mainloop()
    finally:
        core.stop()
    return 0


__all__ = [
    "CoreProcessManager",
    "LauncherConfig",
    "LauncherConfigStore",
    "OrionDesktopLauncher",
    "run_desktop_launcher",
]
