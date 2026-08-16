from __future__ import annotations

import io
import json

import orion.voice_runtime_worker as subject


class _Result:
    def model_dump(self, mode: str = "python") -> dict[str, object]:
        assert mode == "json"
        return {"ok": True, "message": "voice test ok", "stages": {"whisper_ready": True}}


def _run(monkeypatch, commands: list[object], *, ready: bool = True) -> tuple[int, list[dict[str, object]]]:
    input_text = "\n".join(json.dumps(item) if not isinstance(item, str) else item for item in commands)
    if input_text:
        input_text += "\n"
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    monkeypatch.setattr(subject.sys, "stdin", stdin)
    monkeypatch.setattr(subject.sys, "stdout", stdout)
    monkeypatch.setattr(subject, "ensure_runtime", lambda: ("cli", "model"))
    monkeypatch.setattr(subject, "runtime_ready", lambda: ready)
    monkeypatch.setattr(subject, "run_conversational_audio_test", lambda: _Result())
    code = subject.main()
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    return code, replies


def test_worker_handles_ping_conversation_error_and_shutdown(monkeypatch) -> None:
    code, replies = _run(
        monkeypatch,
        [
            {"action": "ping"},
            {"action": "conversation_test"},
            {"action": "unknown"},
            "not-json",
            {"action": "shutdown"},
        ],
    )

    assert code == 0
    assert replies[0] == {"ok": True, "event": "ready", "whisper_ready": True}
    assert replies[1] == {"ok": True, "state": "ready", "whisper_ready": True}
    assert replies[2]["ok"] is True
    result = replies[2]["result"]
    assert isinstance(result, dict)
    assert result["message"] == "voice test ok"
    assert replies[3]["ok"] is False
    assert "Unsupported Voice worker action" in str(replies[3]["error"])
    assert replies[4]["ok"] is False
    assert replies[5] == {"ok": True, "state": "stopping"}


def test_worker_reports_runtime_startup_failure(monkeypatch) -> None:
    stdout = io.StringIO()
    monkeypatch.setattr(subject.sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(subject.sys, "stdout", stdout)

    def fail_runtime():
        raise RuntimeError("whisper payload missing")

    monkeypatch.setattr(subject, "ensure_runtime", fail_runtime)
    code = subject.main()
    reply = json.loads(stdout.getvalue().strip())

    assert code == 2
    assert reply["ok"] is False
    assert reply["event"] == "startup"
    assert "whisper payload missing" in reply["error"]


def test_reply_writes_unicode_json(monkeypatch) -> None:
    stdout = io.StringIO()
    monkeypatch.setattr(subject.sys, "stdout", stdout)
    subject._reply({"ok": True, "message": "Связь установлена"})
    assert json.loads(stdout.getvalue())["message"] == "Связь установлена"
