from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace

from orion.launcher_lifecycle import LauncherVoiceLifecycleMixin
from orion.voice_runtime import VoiceRuntimeSupervisor


class _FakeProcess:
    def __init__(self, replies: list[dict[str, object]], pid: int = 321) -> None:
        self.pid = pid
        self.stdin = StringIO()
        self.stdout = StringIO("".join(json.dumps(item) + "\n" for item in replies))
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
        ]
    )
    supervisor._process = process  # type: ignore[assignment]

    result = supervisor.conversation_test()

    assert result["ok"] is True
    commands = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert [item["action"] for item in commands] == ["ping", "conversation_test", "ping"]
    assert supervisor.status().worker_alive is True


def test_voice_supervisor_shutdown_requests_graceful_worker_exit() -> None:
    supervisor = VoiceRuntimeSupervisor()
    process = _FakeProcess([{"ok": True, "state": "stopping"}])
    supervisor._process = process  # type: ignore[assignment]

    status = supervisor.shutdown()

    assert status.state == "stopped"
    assert json.loads(process.stdin.getvalue().strip())["action"] == "shutdown"
    assert process.terminated is False
    assert process.killed is False


class _LifecycleHarness(LauncherVoiceLifecycleMixin):
    def __init__(self) -> None:
        self._really_exiting = False
        self.events: list[str] = []
        self.core = SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            shutdown=lambda: self.events.append("core_shutdown"),
            stop=lambda: self.events.append("core_stop"),
        )
        self.root = SimpleNamespace(destroy=lambda: self.events.append("launcher_destroy"))
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
