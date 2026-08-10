from __future__ import annotations

import pytest

from orion import windows_tray
from orion.windows_tray import TrayUnavailable, WindowsTrayController


def test_tray_is_unavailable_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(windows_tray.os, "name", "posix")
    tray = WindowsTrayController(lambda: None, lambda: None)
    assert tray.supported is False
    with pytest.raises(TrayUnavailable):
        tray.start()


def test_stop_without_started_icon_is_safe() -> None:
    tray = WindowsTrayController(lambda: None, lambda: None)
    tray.stop()
