from __future__ import annotations

from types import SimpleNamespace

from orion.launcher_shell import OrionLauncher


class _Root:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _Tray:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _Core:
    def __init__(self) -> None:
        self.stop_called = False
        self.shutdown_called = False
        self.detach_called = False

    def stop(self) -> None:
        self.stop_called = True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def detach(self) -> None:
        self.detach_called = True


def test_launcher_exit_closes_ui_and_tray_without_touching_core() -> None:
    root = _Root()
    tray = _Tray()
    core = _Core()
    launcher = SimpleNamespace(root=root, core=core, _tray=tray, _really_exiting=False)

    OrionLauncher.exit_application(launcher)

    assert launcher._really_exiting is True
    assert tray.stopped is True
    assert root.destroyed is True
    assert core.stop_called is False
    assert core.shutdown_called is False
    assert core.detach_called is False
