from __future__ import annotations

import json
import subprocess
from io import StringIO
from types import SimpleNamespace

import pytest

import orion.launcher_lifecycle as lifecycle_subject
import orion.voice_runtime as runtime_subject
from orion.launcher_lifecycle import LauncherVoiceLifecycleMixin
from orion.voice_runtime import VoiceRuntimeSupervisor


class _FakeProcess:
    def __init__(self, replies: list[dict[str, object]], pid: int = 321) -> None:
        self.pid = pid
        self.stdin = StringIO()
        self.stdout = StringIO("".join(json.dumps(item) + "\n" for item in replies))
        self.stderr = None
        self._returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):  # noqa: ANN201
        return self._returncode

    def wait(self, timeout=None):  # noqa: ANN001, ANN201
        self._returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = 0

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9


def test_voice_supervisor_reuses_live_worker_for_conversation() -> None:
    supervisor = VoiceRuntimeSupervisor()
    process = _FakeProcess(
        [
            {"ok": True, "state": "ready", "whisper_ready": True},
            {"ok": True, "result": {"ok": True, "stages": {}, "message": "ok"}},
            {"ok": True, "state": "ready", "whisper_ready": True},
            {"ok": True, "state": "ready", "whisper_ready": True},
        ]
    )
    supervisor._process = process  # type: ignore[assignment]

    result = supervisor.conversation_test()

    assert result["ok"] is True
    commands = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert [item["action"] for item in commands] == ["ping", "conversation_test", "ping"]
    assert supervisor.status().worker_alive is True


def test_voice_supervisor_starts_worker_and_reports_ready(monkeypatch) -> None:
    supervisor = VoiceRuntimeSupervisor()
    process = _FakeProcess([{"ok": True, "event": "ready", "whisper_ready": True}], pid=777)
    monkeypatch.setattr(supervisor, "_command", lambda: ["voice-worker"])
    monkeypatch.setattr(runtime_subject.subprocess, "Popen", lambda *args, **kwargs: process)

    status = supervisor.ensure_ready()

    assert status.state == "ready"
    assert status.worker_alive is True
    assert status.whisper_ready is True
    assert status.pid == 777


def test_voice_supervisor_rejects_failed_startup(monkeypatch) -> None:
    supervisor = VoiceRuntimeSupervisor()
    process = _FakeProcess([{"ok": False, "event": "startup", "error": "Whisper missing"}])
    monkeypatch.setattr(supervisor, "_command", lambda: ["voice-worker"])
    monkeypatch.setattr(runtime_subject.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(RuntimeError, match="Whisper missing"):
        supervisor.ensure_ready()

    assert process.terminated is True
    assert supervisor.status().state == "stopped"


def test_voice_supervisor_status_handles_broken_control_channel() -> None:
    supervisor = VoiceRuntimeSupervisor()
    process = _FakeProcess([])
    supervisor._process = process  # type: ignore[assignment]

    status = supervisor.status()

    assert status.state == "error"
    assert status.worker_alive is True
    assert "closed its control channel" in status.message


def test_voice_supervisor_shutdown_requests_graceful_worker_exit() -> None:
    supervisor = VoiceRuntimeSupervisor()
    process = _FakeProcess([{"ok": True, "state": "stopping"}])
    supervisor._process = process  # type: ignore[assignment]

    status = supervisor.shutdown()

    assert status.state == "stopped"
    assert json.loads(process.stdin.getvalue().strip())["action"] == "shutdown"
    assert process.terminated is False
    assert process.killed is False


def test_voice_supervisor_force_kills_worker_after_timeout() -> None:
    supervisor = VoiceRuntimeSupervisor()

    class StuckProcess(_FakeProcess):
        def wait(self, timeout=None):  # noqa: ANN001, ANN201
            if not self.killed:
                raise subprocess.TimeoutExpired("voice", timeout)
            self._returncode = -9
            return -9

        def terminate(self) -> None:
            self.terminated = True

    process = StuckProcess([])
    supervisor._process = process  # type: ignore[assignment]

    supervisor._terminate_unlocked()

    assert process.terminated is True
    assert process.killed is True
    assert supervisor.status().state == "stopped"


class _LifecycleHarness(LauncherVoiceLifecycleMixin):
    def __init__(self) -> None:
        self._really_exiting = False
        self.events: list[str] = []
        self.core = SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            shutdown=lambda: self.events.append("core_shutdown"),
            stop=lambda: self.events.append("core_stop"),
        )
        self.root = SimpleNamespace(
            destroy=lambda: self.events.append("launcher_destroy"),
            after=lambda delay, callback: callback(),
        )
        self._tray = SimpleNamespace(stop=lambda: self.events.append("tray_stop"))

    def _voice_request(self, path: str, *, timeout: float = 30.0):  # noqa: ANN201
        self.events.append(path)
        return {"state": "stopped", "worker_alive": False, "whisper_ready": False}


def test_explicit_exit_orders_voice_before_core_before_launcher() -> None:
    launcher = _LifecycleHarness()

    launcher.exit_application()

    assert launcher.events == [
        "tray_stop",
        "/v1/windows-audio/voice/shutdown",
        "core_shutdown",
        "launcher_destroy",
    ]


def test_explicit_exit_is_idempotent() -> None:
    launcher = _LifecycleHarness()
    launcher.exit_application()
    launcher.exit_application()
    assert launcher.events.count("launcher_destroy") == 1


def test_ensure_voice_ready_accepts_only_full_ready_state() -> None:
    launcher = _LifecycleHarness()
    launcher._voice_request = lambda path, timeout=30.0: {  # type: ignore[method-assign]
        "state": "ready",
        "worker_alive": True,
        "whisper_ready": True,
        "pid": 42,
    }
    assert launcher._ensure_voice_ready()["pid"] == 42


def test_ensure_voice_ready_rejects_partial_readiness() -> None:
    launcher = _LifecycleHarness()
    launcher._voice_request = lambda path, timeout=30.0: {  # type: ignore[method-assign]
        "state": "ready",
        "worker_alive": True,
        "whisper_ready": False,
        "message": "Whisper is not ready",
    }
    with pytest.raises(RuntimeError, match="Whisper is not ready"):
        launcher._ensure_voice_ready()


def test_voice_request_decodes_core_json(monkeypatch) -> None:
    launcher = _LifecycleHarness()

    class Response:
        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args):  # noqa: ANN002, ANN204
            return False

        def read(self) -> bytes:
            return b'{"state":"ready","worker_alive":true,"whisper_ready":true}'

    monkeypatch.setattr(lifecycle_subject.urllib.request, "urlopen", lambda request, timeout: Response())
    payload = LauncherVoiceLifecycleMixin._voice_request(launcher, "/voice/ensure", timeout=1.0)
    assert payload["whisper_ready"] is True


def test_voice_request_wraps_invalid_json(monkeypatch) -> None:
    launcher = _LifecycleHarness()

    class Response:
        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args):  # noqa: ANN002, ANN204
            return False

        def read(self) -> bytes:
            return b"not-json"

    monkeypatch.setattr(lifecycle_subject.urllib.request, "urlopen", lambda request, timeout: Response())
    with pytest.raises(RuntimeError, match="Voice lifecycle API unavailable"):
        LauncherVoiceLifecycleMixin._voice_request(launcher, "/voice/ensure")
