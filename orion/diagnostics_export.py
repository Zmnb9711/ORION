from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def reveal_in_file_manager(bundle: Path) -> None:
    """Reveal a diagnostic bundle in the native file manager."""

    path = bundle.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", "/select,", str(path)])  # noqa: S603,S607
        return
    raise OSError("Opening the diagnostics folder is only supported by the Windows launcher")


def copy_diagnostics_bundle(bundle: Path, destination: Path) -> Path:
    """Copy a completed diagnostics ZIP without moving or deleting the original."""

    source = bundle.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    target = destination.expanduser().resolve()
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target
