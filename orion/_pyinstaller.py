from __future__ import annotations

from pathlib import Path


def get_hook_dirs() -> list[str]:
    return [str(Path(__file__).with_name("pyinstaller_hooks"))]
