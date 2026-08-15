from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import orion.core_process as subject


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def test_detach_forgets_owned_process_without_terminating(tmp_path: Path) -> None:
    manager = subject.CoreProcessManager("127.0.0.1", 8000, tmp_path)
    process = FakeProcess()
    manager._process = process
    manager._owns_process = True

    manager.detach()

    assert process.terminated is False
    assert process.killed is False
    assert manager._process is None
    assert manager.owns_process is False


def test_shutdown_terminates_owned_process(tmp_path: Path) -> None:
    manager = subject.CoreProcessManager("127.0.0.1", 8000, tmp_path)
    process = FakeProcess()
    manager._process = process
    manager._owns_process = True

    manager.shutdown()

    assert process.terminated is True
    assert manager._process is None
    assert manager.owns_process is False


def test_core_environment_sets_role_and_drops_launcher_routing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ORION_CORE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("ORION_TEST_KEEP", "yes")
    manager = subject.CoreProcessManager("127.0.0.1", 8000, tmp_path)

    env = manager._core_environment()

    assert env["ORION_RUNTIME_DIR"] == str(tmp_path)
    assert env["ORION_PROCESS_ROLE"] == "core"
    assert "ORION_CORE_BASE_URL" not in env
    assert env["ORION_TEST_KEEP"] == "yes"


def test_start_uses_executable_directory_and_normal_process_flags(monkeypatch, tmp_path: Path) -> None:
    core_dir = tmp_path / "Core"
    core_dir.mkdir()
    executable = core_dir / "ORION-Core.exe"
    executable.write_bytes(b"x")
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return FakeProcess()

    manager = subject.CoreProcessManager("127.0.0.1", 8123, tmp_path / "runtime")
    monkeypatch.setattr(manager, "healthy", lambda timeout=0.5: False)
    monkeypatch.setattr(manager, "_command", lambda: [str(executable), "--host", "127.0.0.1", "--port", "8123"])
    monkeypatch.setattr(subject.subprocess, "Popen", fake_popen)

    manager.start()

    assert captured["cwd"] == str(core_dir)
    assert captured["creationflags"] == 0
    assert captured["env"]["ORION_PROCESS_ROLE"] == "core"
    assert manager.owns_process is True
