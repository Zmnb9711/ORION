from __future__ import annotations

import io
import json

import orion.voice_runtime_worker as subject


class _Result:
    def model_dump(self, mode: str = "python") -> dict[str, object]:
        assert mode == "json"
        return {
            "ok": True,
            "recognized_text": "Привет как дела",
            "input_samplerate": 48000,
            "message": "Whisper transcription completed",
        }


def _run(monkeypatch, commands: list[object], *, ready: bool = True) -> tuple[int, list[dict[str, object]]]:
    input_text = "\n".join(json.dumps(item) if not isinstance(item, str) else item for item in commands)
    if input_text:
        input_text += "\n"
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    monkeypatch.setattr(subject.sys, "stdin", stdin)
    monkeypatch.setattr(subject.sys, "stdout", stdout)
    monkeypatch.setattr(subject, "runtime_ready", lambda: ready)
    monkeypatch.setattr(subject, "capture_and_recognize_for_test", lambda: _Result())
    code = subject.main()
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    return code, replies


def test_worker_handles_ping_transcription_error_and_shutdown(monkeypatch) -> None:
    code, replies = _run(
        monkeypatch,
        [
            {"action": "ping"},
            {"action": "transcribe_test"},
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
    assert result["recognized_text"] == "Привет как дела"
    assert result["input_samplerate"] == 48000
    assert "response" not in result
    assert replies[3]["ok"] is False
    assert "Unsupported Voice worker action" in str(replies[3]["error"])
    assert replies[4]["ok"] is False
    assert replies[5] == {"ok": True, "state": "stopping"}


def test_worker_has_no_sapi_or_core_response_path() -> None:
    source_names = set(subject.__dict__)
    assert "WindowsSapiBackend" not in source_names
    assert "play_response_for_test" not in source_names
    assert "run_conversational_audio_test" not in source_names


def test_worker_refuses_start_when_stt_not_installed(monkeypatch) -> None:
    code, replies = _run(monkeypatch, [], ready=False)

    assert code == 2
    assert replies == [
        {
            "ok": False,
            "event": "startup",
            "error": "Whisper medium is not installed. Use DOWNLOAD & INSTALL STT in Launcher first.",
        }
    ]


def test_worker_never_provisions_stt_implicitly() -> None:
    assert not hasattr(subject, "ensure_runtime")


def test_reply_writes_unicode_json(monkeypatch) -> None:
    stdout = io.StringIO()
    monkeypatch.setattr(subject.sys, "stdout", stdout)
    subject._reply({"ok": True, "message": "Связь установлена"})
    assert json.loads(stdout.getvalue())["message"] == "Связь установлена"
