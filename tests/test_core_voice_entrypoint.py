from __future__ import annotations

from pathlib import Path

import pytest

import orion.core_main as core_main
import orion.voice_runtime_worker as voice_worker_module
import orion.windows_audio_worker_api as audio_api
from orion.audio_conversation_test import ConversationalAudioTestResult
from orion.voice_runtime import VoiceRuntimeStatus


def test_runtime_root_uses_configured_directory(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "runtime-home"
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(target))
    assert core_main._runtime_root() == target.resolve()
    assert target.is_dir()


def test_startup_log_records_stage_and_detail(tmp_path: Path) -> None:
    core_main._startup_log(tmp_path, "voice_ready", "pid=42")
    text = (tmp_path / "core-startup.log").read_text(encoding="utf-8")
    assert "voice_ready | pid=42" in text


def test_core_main_dispatches_to_hosted_voice_worker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(core_main, "_ensure_stdio", lambda: None)
    monkeypatch.setattr(core_main, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(voice_worker_module, "main", lambda: 17)

    assert core_main.main(["--voice-worker"]) == 17
    assert core_main.os.environ["ORION_PROCESS_ROLE"] == "voice"


def test_core_main_runs_api_server_and_logs_lifecycle(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, int, str]] = []
    monkeypatch.setattr(core_main, "_ensure_stdio", lambda: None)
    monkeypatch.setattr(core_main, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(
        core_main.uvicorn,
        "run",
        lambda app, host, port, log_level: calls.append((host, port, log_level)),
    )

    assert core_main.main(["--host", "127.0.0.9", "--port", "8129"]) == 0
    assert calls == [("127.0.0.9", 8129, "info")]
    assert core_main.os.environ["ORION_PROCESS_ROLE"] == "core"
    log = (tmp_path / "core-startup.log").read_text(encoding="utf-8")
    assert "uvicorn_start" in log
    assert "uvicorn_exit" in log


def test_core_main_logs_fatal_server_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(core_main, "_ensure_stdio", lambda: None)
    monkeypatch.setattr(core_main, "_runtime_root", lambda: tmp_path)

    def fail_server(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("server failed")

    monkeypatch.setattr(core_main.uvicorn, "run", fail_server)
    with pytest.raises(RuntimeError, match="server failed"):
        core_main.main([])
    assert "fatal | RuntimeError: server failed" in (tmp_path / "core-startup.log").read_text(encoding="utf-8")


def test_voice_runtime_api_status_and_ensure(monkeypatch) -> None:
    status = VoiceRuntimeStatus(state="ready", worker_alive=True, whisper_ready=True, pid=55)
    monkeypatch.setattr(audio_api.voice_runtime, "status", lambda: status)
    monkeypatch.setattr(audio_api.voice_runtime, "ensure_ready", lambda: status)

    assert audio_api.voice_status().pid == 55
    assert audio_api.ensure_voice().whisper_ready is True


def test_voice_runtime_api_conversation_and_shutdown(monkeypatch) -> None:
    result = ConversationalAudioTestResult(
        ok=True,
        recognized_text="Привет как дела",
        stages={"whisper_ready": True},
        message="Дела отлично. Связь установлена.",
    )
    stopped = VoiceRuntimeStatus(state="stopped", worker_alive=False, whisper_ready=False)
    monkeypatch.setattr(audio_api.voice_runtime, "conversation_test", lambda: result.model_dump(mode="json"))
    monkeypatch.setattr(audio_api.voice_runtime, "shutdown", lambda: stopped)

    assert audio_api.conversation_audio_test().ok is True
    assert audio_api.shutdown_voice().state == "stopped"


def test_voice_runtime_api_maps_ensure_failure_to_503(monkeypatch) -> None:
    def fail_ready():
        raise RuntimeError("Whisper unavailable")

    monkeypatch.setattr(audio_api.voice_runtime, "ensure_ready", fail_ready)
    with pytest.raises(audio_api.HTTPException) as captured:
        audio_api.ensure_voice()
    assert captured.value.status_code == 503
    assert "Whisper unavailable" in str(captured.value.detail)


def test_voice_runtime_api_contains_conversation_failure(monkeypatch) -> None:
    def fail_test():
        raise RuntimeError("microphone unavailable")

    monkeypatch.setattr(audio_api.voice_runtime, "conversation_test", fail_test)
    result = audio_api.conversation_audio_test()
    assert result.ok is False
    assert result.stages["voice_worker_ready"] is False
    assert "microphone unavailable" in result.message
