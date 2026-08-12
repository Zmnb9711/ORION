from __future__ import annotations

import traceback
from pathlib import Path
from tkinter import Tk, messagebox

# Compatibility surface kept for existing imports while production launch is
# moved onto a separate ORION Core process.
from orion.core_process import CoreProcessManager
from orion.desktop_app import LauncherConfig, LauncherConfigStore, OrionDesktopLauncher
from orion.desktop_product_launcher import WindowsOrionProductLauncher


def _install_tk_exception_boundary(root: Tk, runtime_dir: Path) -> None:
    log_path = runtime_dir / "launcher-ui-errors.log"

    def report(exc_type, exc_value, exc_traceback) -> None:  # noqa: ANN001
        runtime_dir.mkdir(parents=True, exist_ok=True)
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(detail)
            if not detail.endswith("\n"):
                handle.write("\n")
        try:
            messagebox.showerror(
                "ORION Launcher",
                f"A Launcher operation failed: {exc_value}\n\nDetails were written to {log_path}",
                parent=root,
            )
        except Exception:
            # Never let the exception-reporting path recursively fail Tk.
            pass

    root.report_callback_exception = report  # type: ignore[method-assign]


def run_desktop_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    core.start()
    try:
        root = Tk()
        _install_tk_exception_boundary(root, runtime_dir)
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
