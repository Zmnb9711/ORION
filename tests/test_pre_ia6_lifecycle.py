from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from orion.core_lifecycle import CoreLifecycleController
from orion.core_process import CoreProcessManager
from orion.desktop_app_windows import WindowsOrionDesktopLauncher
from orion.desktop_launcher_field_fixed import FieldFixedAudioLauncher


def _owned_manager(tmp_path: Path) -> tuple[CoreProcessManager, Mock]:
    manager = CoreProcessManager("127.0.0.1", 8123, tmp_path / "runtime")
    process = Mock()
    process.pid = 5151
    process.poll.return_value = None
    manager._process = process
    manager._owns_process = True
    manager._shutdown_token = "owned-token"
    return manager, process


def _free_port(*, udp: bool = False) -> int:
    kind = socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_window_x_hides_launcher_and_preserves_tray_and_owned_core() -> None:
    events: list[str] = []
    core = SimpleNamespace(
        owns_process=True,
        record_lifecycle=lambda event, **fields: events.append(event),
        shutdown=lambda: events.append("FORBIDDEN_SHUTDOWN"),
    )
    launcher = SimpleNamespace(
        _really_exiting=False,
        config=SimpleNamespace(minimize_to_tray=True),
        _tray=SimpleNamespace(start=lambda: events.append("tray_started")),
        root=SimpleNamespace(withdraw=lambda: events.append("window_hidden")),
        core=core,
        exit_application=lambda: events.append("FORBIDDEN_EXIT"),
    )

    WindowsOrionDesktopLauncher.close(launcher)

    assert events == ["tray_started", "window_close_to_tray", "window_hidden"]
    assert core.owns_process is True


def test_tray_exit_orders_core_before_tray_and_launcher_cleanup() -> None:
    events: list[str] = []
    launcher = object.__new__(FieldFixedAudioLauncher)
    launcher._really_exiting = False
    launcher._stop_realtime_before_exit = lambda: events.append("sessions_stopped")
    launcher._tray = SimpleNamespace(stop=lambda: events.append("tray_removed"))
    launcher.root = SimpleNamespace(destroy=lambda: events.append("launcher_destroyed"))
    launcher.core = SimpleNamespace(
        owns_process=True,
        managed_pid=5151,
        record_lifecycle=lambda event, **fields: events.append(event),
        shutdown=lambda: events.append("core_shutdown_complete"),
    )

    launcher.exit_application()

    assert events == [
        "explicit_tray_exit_requested",
        "sessions_stopped",
        "core_shutdown_complete",
        "tray_removed",
        "launcher_exit",
        "launcher_destroyed",
    ]


def test_launcher_still_exits_if_core_shutdown_boundary_raises() -> None:
    events: list[str] = []
    launcher = object.__new__(FieldFixedAudioLauncher)
    launcher._really_exiting = False
    launcher._stop_realtime_before_exit = lambda: None
    launcher._tray = SimpleNamespace(stop=lambda: events.append("tray_removed"))
    launcher.root = SimpleNamespace(destroy=lambda: events.append("launcher_destroyed"))

    def fail() -> None:
        raise RuntimeError("controlled failure")

    launcher.core = SimpleNamespace(
        owns_process=True,
        managed_pid=5151,
        record_lifecycle=lambda event, **fields: events.append(event),
        shutdown=fail,
    )

    with pytest.raises(RuntimeError, match="controlled failure"):
        launcher.exit_application()

    assert events[-3:] == ["tray_removed", "launcher_exit", "launcher_destroyed"]


def test_token_controller_accepts_only_bound_owner_token() -> None:
    controller = CoreLifecycleController()
    calls: list[str] = []
    controller.bind("owner-token", lambda: calls.append("shutdown"))

    assert controller.request_shutdown(None) is False
    assert controller.request_shutdown("wrong-token") is False
    assert controller.request_shutdown("owner-token") is True
    assert calls == ["shutdown"]

    controller.unbind()
    assert controller.request_shutdown("owner-token") is False


def test_graceful_timeout_terminates_only_owned_child(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager, process = _owned_manager(tmp_path)
    monkeypatch.setattr(manager, "_request_graceful_shutdown", lambda token: True)
    monkeypatch.setattr(manager, "_wait_for_udp_release", lambda: True)
    waits = iter([False, True])

    def wait(_process: Mock, _timeout: float) -> bool:
        exited = next(waits)
        if exited:
            process.poll.return_value = 0
        return exited

    monkeypatch.setattr(manager, "_wait_for_process", wait)

    result = manager.shutdown()

    process.terminate.assert_called_once_with()
    process.kill.assert_not_called()
    assert result.fallback_terminate is True
    assert result.process_exited is True


def test_second_timeout_kills_only_owned_child(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager, process = _owned_manager(tmp_path)
    monkeypatch.setattr(manager, "_request_graceful_shutdown", lambda token: True)
    monkeypatch.setattr(manager, "_wait_for_udp_release", lambda: True)
    waits = iter([False, False, True])

    def wait(_process: Mock, _timeout: float) -> bool:
        exited = next(waits)
        if exited:
            process.poll.return_value = 0
        return exited

    monkeypatch.setattr(manager, "_wait_for_process", wait)

    result = manager.shutdown()

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert result.fallback_kill is True
    assert result.process_exited is True


def test_unreachable_graceful_endpoint_uses_owned_handle_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager, process = _owned_manager(tmp_path)
    monkeypatch.setattr(manager, "_request_graceful_shutdown", lambda token: False)
    monkeypatch.setattr(manager, "_wait_for_udp_release", lambda: True)

    def exit_after_terminate(_process: Mock, _timeout: float) -> bool:
        process.poll.return_value = 0
        return True

    monkeypatch.setattr(manager, "_wait_for_process", exit_after_terminate)

    result = manager.shutdown()

    process.terminate.assert_called_once_with()
    assert result.graceful_requested is False
    assert result.fallback_terminate is True
    assert result.process_exited is True


def test_external_core_is_not_adopted_by_pid_path_name_or_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = CoreProcessManager("127.0.0.1", 8123, tmp_path / "runtime")
    (manager.runtime_dir).mkdir(parents=True)
    (manager.runtime_dir / "orion-core.pid").write_text("5151", encoding="ascii")
    monkeypatch.setattr(manager, "healthy", lambda: True)
    popen = Mock(side_effect=AssertionError("must not spawn"))
    monkeypatch.setattr(subprocess, "Popen", popen)

    manager.start()
    result = manager.shutdown()

    assert manager.owns_process is False
    assert result.owned is False
    assert result.fallback_terminate is False
    popen.assert_not_called()


def test_already_dead_and_disappearing_owned_core_need_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager, process = _owned_manager(tmp_path)
    process.poll.return_value = 0
    monkeypatch.setattr(manager, "_request_graceful_shutdown", Mock(side_effect=AssertionError("no request")))
    monkeypatch.setattr(manager, "_wait_for_udp_release", lambda: True)

    result = manager.shutdown()

    process.terminate.assert_not_called()
    process.kill.assert_not_called()
    assert result.process_exited is True

    manager, process = _owned_manager(tmp_path)

    def disappears(_token: str) -> bool:
        process.poll.return_value = 0
        return False

    monkeypatch.setattr(manager, "_request_graceful_shutdown", disappears)
    monkeypatch.setattr(manager, "_wait_for_udp_release", lambda: True)
    result = manager.shutdown()
    process.terminate.assert_not_called()
    assert result.process_exited is True


def test_lifecycle_diagnostics_are_bounded_and_never_include_token(tmp_path: Path) -> None:
    manager = CoreProcessManager("127.0.0.1", 8123, tmp_path / "runtime")
    manager.LIFECYCLE_LOG_LIMIT = 1024
    for index in range(100):
        manager.record_lifecycle("bounded_event", pid=index, token="must-not-be-written")

    content = manager._lifecycle_log_path.read_text(encoding="utf-8")
    assert len(content.encode("utf-8")) < 2048
    assert "must-not-be-written" not in content
    assert all(json.loads(line)["event"] == "bounded_event" for line in content.splitlines())


def test_owned_core_gracefully_releases_isolated_udp_and_restarts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    http_port = _free_port()
    udp_port = _free_port(udp=True)
    monkeypatch.setenv("ORION_FLIGHT_BRIDGE_HOST", "127.0.0.1")
    monkeypatch.setenv("ORION_FLIGHT_BRIDGE_TELEMETRY_PORT", str(udp_port))
    monkeypatch.setenv("ORION_EVENT_LOG_PATH", str(tmp_path / "events.jsonl"))

    def run_once(runtime: Path) -> None:
        manager = CoreProcessManager("127.0.0.1", http_port, runtime)
        manager.start()
        process = manager._process
        assert process is not None
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and not manager.healthy():
            if process.poll() is not None:
                pytest.fail(f"isolated Core exited during startup: {process.returncode}")
            time.sleep(0.1)
        assert manager.healthy()
        assert manager._udp_port_available("127.0.0.1", udp_port) is False

        result = manager.shutdown()

        assert result.graceful_requested is True
        assert result.graceful_exit is True
        assert result.fallback_terminate is False
        assert result.process_exited is True
        assert result.udp_released is True
        assert manager._udp_port_available("127.0.0.1", udp_port) is True

    run_once(tmp_path / "runtime-one")
    run_once(tmp_path / "runtime-two")
