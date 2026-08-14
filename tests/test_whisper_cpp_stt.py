from __future__ import annotations

import os
import wave
from pathlib import Path

import pytest

from orion import whisper_cpp_stt as stt


def _write_wav(path: Path, sample_rate: int = 48000, channels: int = 1) -> None:
    frames = (b"\x00\x00" * channels) * sample_rate
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)


def test_medium_model_is_canonical_default() -> None:
    assert stt.WHISPER_MODEL_NAME == "medium"
    assert stt.WHISPER_MODEL_FILENAME == "ggml-medium.bin"
    assert stt.WHISPER_MODEL_SHA1 == "fd9727b6e1217c2f614f9b698455c4ffd82463b4"


def test_thread_budget_defaults_to_four(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORION_WHISPER_THREADS", raising=False)
    assert stt.configured_threads() == 4
    monkeypatch.setenv("ORION_WHISPER_THREADS", "99")
    assert stt.configured_threads() == 16


def test_runtime_path_uses_orion_runtime_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("ORION_WHISPER_ROOT", raising=False)
    assert stt.stt_root() == tmp_path / "stt" / "whisper.cpp"


def test_prepare_input_resamples_to_whisper_format(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    target = tmp_path / "target.wav"
    _write_wav(source, sample_rate=48000, channels=1)
    stt._prepare_input_wav(source, target)
    with wave.open(str(target), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 16000


def test_recognizer_forces_cpu_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    cli = tmp_path / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")
    model = tmp_path / "ggml-medium.bin"
    _write_wav(source, sample_rate=16000)
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    monkeypatch.setattr(stt, "ensure_runtime", lambda: (cli, model))

    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = "Привет, как дела?"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        return Completed()

    monkeypatch.setattr(stt.subprocess, "run", fake_run)
    text = stt.recognize_wav(source, language="ru")
    command = captured["command"]
    assert isinstance(command, list)
    assert "--no-gpu" in command
    assert command[command.index("--threads") + 1] == "4"
    assert command[command.index("--language") + 1] == "ru"
    assert text == "Привет, как дела?"
