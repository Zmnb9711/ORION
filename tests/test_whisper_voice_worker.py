from pathlib import Path
from types import SimpleNamespace

import pytest

from orion import whisper_voice_worker as worker


def test_stream_parser_drops_runtime_noise() -> None:
    assert worker._normalize_transcript_line("main: using VAD\n") == ""
    assert worker._normalize_transcript_line("whisper_init: loading model\n") == ""
    assert worker._normalize_transcript_line("  Привет, как дела?  \n") == "Привет, как дела?"


def test_stream_command_is_live_vad_cpu_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stream = tmp_path / "whisper-stream.exe"
    model = tmp_path / "ggml-medium.bin"
    stream.write_bytes(b"stream")
    model.write_bytes(b"model")
    monkeypatch.setattr(worker, "whisper_stream_path", lambda: stream)
    monkeypatch.setattr(worker, "whisper_model_path", lambda: model)
    monkeypatch.setattr(worker, "configured_threads", lambda: 4)
    command = worker.build_stream_command()
    assert command[0] == str(stream)
    assert command[command.index("--model") + 1] == str(model)
    assert command[command.index("--language") + 1] == "ru"
    assert command[command.index("--step") + 1] == "0"
    assert "--vad-thold" in command
    assert "--no-gpu" in command


def test_post_text_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return b'{"heard":"\\u041f\\u0440\\u0438\\u0432\\u0435\\u0442. \\u041a\\u0430\\u043a \\u0434\\u0435\\u043b\\u0430?","reply":"\\u0412\\u0441\\u0451 \\u0445\\u043e\\u0440\\u043e\\u0448\\u043e. \\u0421\\u0432\\u044f\\u0437\\u044c \\u0443\\u0441\\u0442\\u0430\\u043d\\u043e\\u0432\\u043b\\u0435\\u043d\\u0430.","matched":true,"tts_requested":true}'

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data.decode("utf-8")
        return Response()

    monkeypatch.setattr(worker.urllib.request, "urlopen", fake_urlopen)
    result = worker._post_text("Привет. Как дела?", core_url="http://127.0.0.1:8765")
    assert captured["url"].endswith("/v1/voice/text")
    assert "Привет. Как дела?" in captured["body"]
    assert result.matched is True
    assert result.reply == "Всё хорошо. Связь установлена."
    assert result.tts_requested is True


def test_worker_bridges_transcript_and_speaks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stream = tmp_path / "whisper-stream.exe"
    stream.write_bytes(b"stream")
    monkeypatch.setattr(worker, "whisper_stream_path", lambda: stream)
    monkeypatch.setattr(worker, "build_stream_command", lambda: [str(stream)])

    class FakeProcess:
        stdout = iter(["main: noise\n", "Привет. Как дела?\n", "Привет. Как дела?\n"])

        def poll(self):
            return 0

        def terminate(self):
            raise AssertionError("completed process should not be terminated")

        def wait(self):
            return 0

    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    seen = []
    spoken = []

    def fake_post(text, *, core_url):
        seen.append(text)
        return worker.VoiceBridgeReply(text, "Всё хорошо. Связь установлена.", True, True)

    monkeypatch.setattr(worker, "_post_text", fake_post)
    monkeypatch.setattr(worker, "_speak", spoken.append)
    assert worker.run_forever(core_url="http://core") == 0
    assert seen == ["Привет. Как дела?"]
    assert spoken == ["Всё хорошо. Связь установлена."]
