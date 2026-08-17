from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from orion import voice_process
from orion.desktop_app_windows import WindowsOrionDesktopLauncher
from orion.desktop_launcher_field_fixed import FieldFixedConversationalAudioLauncher
from orion.voice_process import VoiceProcessManager


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


def test_full_exit_orders_voice_before_core_before_launcher() -> None:
    events: list[str] = []
    launcher = object.__new__(FieldFixedConversationalAudioLauncher)
    launcher._really_exiting = False
    launcher._tray = _Recorder(events, "tray")
    launcher.voice = _Recorder(events, "voice")
    launcher.core = _Recorder(events, "core")
    launcher.root = _Recorder(events, "launcher")

    launcher.exit_application()

    assert events == ["tray", "voice", "core", "launcher"]
    assert launcher._really_exiting is True
    launcher.exit_application()
    assert events == ["tray", "voice", "core", "launcher"]


def test_window_close_to_tray_does_not_shutdown_runtime() -> None:
    events: list[str] = []
    launcher = SimpleNamespace(
        _really_exiting=False,
        config=SimpleNamespace(minimize_to_tray=True),
        _tray=_Recorder(events, "tray-start"),
        root=_Recorder(events, "window-withdraw"),
        exit_application=lambda: events.append("FULL-EXIT"),
    )

    WindowsOrionDesktopLauncher.close(launcher)

    assert events == ["tray-start", "window-withdraw"]
    assert "FULL-EXIT" not in events


class _FakeProcess:
    def __init__(self, *, timeout_once: bool = False) -> None:
        self.pid = 4242
        self.timeout_once = timeout_once
        self.wait_calls: list[float] = []
        self.kill_calls = 0

    def poll(self):  # noqa: ANN201
        return None

    def wait(self, timeout: float):  # noqa: ANN201
        self.wait_calls.append(timeout)
        if self.timeout_once:
            self.timeout_once = False
            raise subprocess.TimeoutExpired(cmd="voice", timeout=timeout)
        return 0

    def kill(self) -> None:
        self.kill_calls += 1


def test_windows_voice_stop_targets_only_owned_pid_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = VoiceProcessManager(tmp_path, "http://127.0.0.1:8000")
    process = _FakeProcess()
    manager._process = process  # type: ignore[assignment]
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(voice_process, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(manager, "_taskkill_tree", lambda pid, *, force: calls.append((pid, force)))

    manager.stop()

    assert calls == [(4242, False)]
    assert process.kill_calls == 0
    assert manager._process is None
    assert manager.status()["state"] == "STOPPED"


def test_windows_voice_stop_force_kills_same_owned_tree_after_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = VoiceProcessManager(tmp_path, "http://127.0.0.1:8000")
    process = _FakeProcess(timeout_once=True)
    manager._process = process  # type: ignore[assignment]
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(voice_process, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(manager, "_taskkill_tree", lambda pid, *, force: calls.append((pid, force)))

    manager.stop()

    assert calls == [(4242, False), (4242, True)]
    assert process.kill_calls == 0
    assert process.wait_calls == [manager.GRACEFUL_STOP_TIMEOUT, manager.FORCE_STOP_TIMEOUT]
