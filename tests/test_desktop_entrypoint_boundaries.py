from __future__ import annotations

import orion.desktop_app_windows as windows_base
import orion.desktop_app_windows_v2 as windows_v2
import orion.desktop_product_launcher as product_launcher


def test_only_product_launcher_exposes_desktop_entry_point() -> None:
    """Legacy visual layers must not be runnable as alternate product launchers."""

    assert not hasattr(windows_base, "run_desktop_launcher")
    assert not hasattr(windows_v2, "run_desktop_launcher")
    assert callable(product_launcher.run_desktop_launcher)
