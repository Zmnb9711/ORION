from __future__ import annotations

import sys
from pathlib import Path

APPROVED_ICON_SHA256 = "4c7059d3d6909442433e550ec8a5582679924f8b12bbbdfdb37d90125258fce0"


def packaged_icon_path() -> Path | None:
    """Return the approved ORION icon when it is present in source or a frozen bundle."""
    roots: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root))
    roots.append(Path(__file__).resolve().parent.parent)
    for root in roots:
        candidate = root / "branding" / "orion.ico"
        if candidate.is_file():
            return candidate
    return None
