from __future__ import annotations

from types import SimpleNamespace

import pytest

import orion.launcher_lifecycle as lifecycle_subject
from orion.launcher_lifecycle import LauncherVoiceLifecycleMixin

READY = {"state": "ready", "worker_alive": True, "whisper_ready": True}


class _ConversationBase:
    def _conversation_core_json(self):  # noqa: ANN201
        return {"ok": True, "message": "audio test complete"}


class _Harness(LauncherVoiceLifecycleMixin, _ConversationBase):
    def __init__(self, replies: list[dict[str, object]]) -> None:
        self.replies = list(replies)
        self.core = SimpleNamespace(base_url="http://127.0.0.1:8000")
        self.root = SimpleNamespace(after=lambda delay, callback: callback())

    def _voice_request(self, path: str, *, timeout: float = 30.0):  # noqa: ANN201
        return self.replies.pop(0)


class _ImmediateThread:
    def __init__(self, *, target, name: str, daemon: bool) -> None:  # noqa: ANN001
        self.target = target
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        self.target()


def test_conversation_uses_ready_worker_and_keeps_it_ready() -> None:
    launcher = _Harness([READY.copy(), READY.copy()])

    result = launcher._conversation_core_json()

    assert result == {"ok": True, "message": "audio test complete"}
    assert launcher.replies == []


def test_conversation_rejects_worker_that_loses_whisper_after_test() -> None:
    after = READY.copy()
    after["whisper_ready"] = False
    launcher = _Harness([READY.copy(), after])

    with pytest.raises(RuntimeError, match="did not remain READY"):
        launcher._conversation_core_json()


def test_launch_dcs_runs_only_after_voice_ready(monkeypatch) -> None:
    launcher = _Harness([READY.copy()])
    events: list[str] = []
    monkeypatch.setattr(lifecycle_subject.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        lifecycle_subject,
        "start_dcs_for_recovery",
        lambda: SimpleNamespace(message="DCS started"),
    )
    monkeypatch.setattr(
        lifecycle_subject.messagebox,
        "showinfo",
        lambda *args, **kwargs: events.append("info"),
    )
    monkeypatch.setattr(
        lifecycle_subject.messagebox,
        "showerror",
        lambda *args, **kwargs: events.append("error"),
    )

    launcher._launch_dcs_async()

    assert events == ["info"]
    assert launcher.replies == []


def test_launch_dcs_stops_when_voice_is_not_ready(monkeypatch) -> None:
    not_ready = {"state": "ready", "worker_alive": True, "whisper_ready": False, "message": "Whisper not ready"}
    launcher = _Harness([not_ready])
    events: list[str] = []
    dcs_started: list[bool] = []
    monkeypatch.setattr(lifecycle_subject.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        lifecycle_subject,
        "start_dcs_for_recovery",
        lambda: dcs_started.append(True),
    )
    monkeypatch.setattr(
        lifecycle_subject.messagebox,
        "showinfo",
        lambda *args, **kwargs: events.append("info"),
    )
    monkeypatch.setattr(
        lifecycle_subject.messagebox,
        "showerror",
        lambda *args, **kwargs: events.append("error"),
    )

    launcher._launch_dcs_async()

    assert events == ["error"]
    assert dcs_started == []
