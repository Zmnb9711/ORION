from __future__ import annotations

from pathlib import Path
from tkinter import Tk

from orion.desktop_app import CoreServer
from orion.desktop_app_windows import WindowsOrionDesktopLauncher
from orion.desktop_product_visual import WindowsProductVisualMixin


class WindowsOrionDesktopLauncherV2(WindowsProductVisualMixin, WindowsOrionDesktopLauncher):
    """Compatibility shim for legacy imports.

    Production code must instantiate WindowsOrionProductLauncher. The visual
    implementation now lives in WindowsProductVisualMixin so the V2 identity is
    no longer part of the canonical launcher inheritance chain.
    """

    def __init__(self, root: Tk, runtime_dir: Path, core: CoreServer) -> None:
        super().__init__(root, runtime_dir, core)
