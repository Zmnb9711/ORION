from __future__ import annotations

from pathlib import Path

import orion.desktop_app_windows as windows_base
import orion.desktop_product_launcher as product_launcher


ROOT = Path(__file__).resolve().parents[1]
LEGACY_V2 = ROOT / "orion" / "desktop_app_windows_v2.py"


def test_only_product_launcher_exposes_desktop_entry_point() -> None:
    """Legacy visual layers must not be runnable as alternate product launchers."""

    assert not hasattr(windows_base, "run_desktop_launcher")
    assert not LEGACY_V2.exists()
    assert callable(product_launcher.run_desktop_launcher)
