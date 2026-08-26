from __future__ import annotations

from types import SimpleNamespace

from orion.desktop_app_windows import WindowsOrionDesktopLauncher
from orion.desktop_launcher_field_fixed import FieldFixedAudioLauncher


class _Recorder:
    def __init__(self, events: list[str], name: str) -> None:
        self.events = events
        self.name = name

    def stop(self) -> None:
        self.events.append(self.name)

    def shutdown(self) -> None:
        self.events.append(self.name)

    def destroy(self) -> None:
        self.events.append(self.name)

    def withdraw(self) -> None:
        self.events.append(self.name)

    def start(self) -> None:
        self.events.append(self.name)

    @property
    def owns_process(self) -> bool:
        return True

    @property
    def managed_pid(self) -> int:
        return 5151

    def record_lifecycle(self, event: str, **_fields: object) -> None:
        self.events.append(event)


def test_full_exit_stops_realtime_provider_before_core_before_launcher() -> None:
    events: list[str] = []
    launcher = object.__new__(FieldFixedAudioLauncher)
    launcher._really_exiting = False
    launcher._tray = _Recorder(events, "tray")
    launcher._stop_realtime_before_exit = lambda: events.append("realtime-stop")
    launcher.core = _Recorder(events, "core")
    launcher.root = _Recorder(events, "launcher")

    launcher.exit_application()

    assert events == [
        "explicit_tray_exit_requested",
        "realtime-stop",
        "core",
        "tray",
        "launcher_exit",
        "launcher",
    ]
    assert launcher._really_exiting is True
    launcher.exit_application()
    assert events[-1] == "launcher"


def test_window_close_to_tray_does_not_shutdown_runtime() -> None:
    events: list[str] = []
    launcher = SimpleNamespace(
        _really_exiting=False,
        config=SimpleNamespace(minimize_to_tray=True),
        _tray=_Recorder(events, "tray-start"),
        root=_Recorder(events, "window-withdraw"),
        core=SimpleNamespace(owns_process=True),
        exit_application=lambda: events.append("FULL-EXIT"),
    )

    WindowsOrionDesktopLauncher.close(launcher)

    assert events == ["tray-start", "window-withdraw"]
    assert "FULL-EXIT" not in events
