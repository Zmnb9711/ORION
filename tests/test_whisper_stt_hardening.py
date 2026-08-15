from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from orion import whisper_cpp_stt as stt


def _bind_ready_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    cli = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-medium.bin"
    source = tmp_path / "input.wav"
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    source.write_bytes(b"wav")
    monkeypatch.setattr(stt, "runtime_ready", lambda: True)
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    return source, cli


def test_legacy_recognition_paths_are_removed() -> None:
    assert not hasattr(stt, "_prepare_input_wav")
    assert not hasattr(stt, "_read_pcm16_mono_16k")
    assert not hasattr(stt, "_force_portable_cpu_backend")
    assert not hasattr(stt, "_run_whisper")


def test_recognizer_uses_original_wav_and_no_window_creation_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, cli = _bind_ready_runtime(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = dict(kwargs)
        output_base = Path(command[command.index("--output-file") + 1])
        output_base.with_suffix(".txt").write_text("Привет как дела", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(stt.subprocess, "run", fake_run)
    assert stt.recognize_wav(source, language="ru") == "Привет как дела"

    command = captured["command"]
    kwargs = captured["kwargs"]
    assert isinstance(command, list)
    assert command[command.index("--file") + 1] == str(source.resolve())
    assert command[command.index("--language") + 1] == "ru"
    assert "--no-gpu" in command
    assert kwargs["cwd"] == str(cli.parent)
    assert "creationflags" not in kwargs
    assert "capture_output" not in kwargs
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None


def test_recognizer_reports_native_windows_status_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, _cli = _bind_ready_runtime(monkeypatch, tmp_path)
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=-1073740791)

    monkeypatch.setattr(stt.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="0xC0000409"):
        stt.recognize_wav(source, language="ru")
    assert calls == 1


def test_recognizer_never_installs_runtime_implicitly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "input.wav"
    source.write_bytes(b"wav")
    monkeypatch.setattr(stt, "runtime_ready", lambda: False)
    with pytest.raises(RuntimeError, match="not prepared"):
        stt.recognize_wav(source)
