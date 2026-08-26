from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import orion.core_process as core_process
from orion.core_process import CoreProcessManager


def test_source_launcher_uses_core_module_entry_point(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ORION_CORE_EXECUTABLE", raising=False)
    monkeypatch.setattr(core_process.sys, "frozen", False, raising=False)
    core = CoreProcessManager("127.0.0.1", 8123, runtime_dir=tmp_path / "runtime")

    command = core._command()

    assert command[0] == core_process.sys.executable
    assert command[1:3] == ["-m", "orion.core_main"]
    assert command[-2:] == ["--port", "8123"]


def test_launcher_honors_explicit_core_executable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ORION_CORE_EXECUTABLE", r"C:\Program Files\ORION\Core\ORION-Core.exe")
    core = CoreProcessManager("127.0.0.1", 8000, runtime_dir=tmp_path / "runtime")

    assert core._command() == [
        r"C:\Program Files\ORION\Core\ORION-Core.exe",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]


def test_launcher_attaches_to_existing_core_without_owning_it(monkeypatch, tmp_path: Path) -> None:
    core = CoreProcessManager("127.0.0.1", 8000, runtime_dir=tmp_path / "runtime")
    monkeypatch.setattr(core, "healthy", lambda: True)

    core.start()

    assert core.owns_process is False
    assert core._process is None


def test_launcher_stop_detaches_without_terminating_owned_core(tmp_path: Path) -> None:
    core = CoreProcessManager("127.0.0.1", 8000, runtime_dir=tmp_path / "runtime")
    process = Mock()
    process.poll.return_value = None
    core._process = process
    core._owns_process = True

    core.stop()

    process.terminate.assert_not_called()
    process.kill.assert_not_called()
    assert core.owns_process is False
    assert core._process is None


def test_explicit_shutdown_gracefully_stops_owned_core(monkeypatch, tmp_path: Path) -> None:
    core = CoreProcessManager("127.0.0.1", 8000, runtime_dir=tmp_path / "runtime")
    process = Mock()
    process.poll.return_value = None
    process.pid = 5151
    core._process = process
    core._owns_process = True
    core._shutdown_token = "bound-token"
    monkeypatch.setattr(core, "_request_graceful_shutdown", lambda token: token == "bound-token")
    monkeypatch.setattr(core, "_wait_for_udp_release", lambda: True)

    def exit_on_wait(*, timeout: float) -> None:
        assert timeout == core.GRACEFUL_STOP_TIMEOUT
        process.poll.return_value = 0

    process.wait.side_effect = exit_on_wait

    result = core.shutdown()

    process.terminate.assert_not_called()
    process.kill.assert_not_called()
    process.wait.assert_called_once_with(timeout=core.GRACEFUL_STOP_TIMEOUT)
    assert result.graceful_requested is True
    assert result.graceful_exit is True
    assert result.process_exited is True
    assert result.udp_released is True
    assert core.owns_process is False
    assert core._process is None


def test_explicit_shutdown_preserves_attached_external_core(tmp_path: Path) -> None:
    core = CoreProcessManager("127.0.0.1", 8000, runtime_dir=tmp_path / "runtime")

    result = core.shutdown()

    assert result.owned is False
    assert result.graceful_requested is False
    assert result.fallback_terminate is False
