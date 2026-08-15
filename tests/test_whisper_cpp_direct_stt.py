from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import orion.whisper_cpp_direct_stt as stt


def test_recognize_passes_original_wav_and_runtime_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = tmp_path / "whisper.cpp"
    runtime.mkdir()
    cli = runtime / "whisper-cli.exe"
    model = runtime / "models" / "ggml-medium.bin"
    model.parent.mkdir()
    cli.write_bytes(b"exe")
    model.write_bytes(b"model")
    source = tmp_path / "native-48000.wav"
    source.write_bytes(b"wav")

    monkeypatch.setattr(stt, "runtime_ready", lambda: True)
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    monkeypatch.setattr(stt, "configured_threads", lambda: 4)
    monkeypatch.setattr(stt, "_hidden_startupinfo", lambda: None)

    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        output_base = Path(command[command.index("--output-file") + 1])
        output_base.with_suffix(".txt").write_text("Привет, как дела?\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(stt.subprocess, "run", fake_run)

    text = stt.recognize_wav(source, language="ru")

    command = seen["command"]
    assert text == "Привет, как дела?"
    assert command[command.index("--file") + 1] == str(source.resolve())
    assert "input-16k.wav" not in " ".join(command)
    assert command[command.index("--threads") + 1] == "4"
    assert command[command.index("--processors") + 1] == "1"
    assert "--no-gpu" in command
    assert seen["cwd"] == str(runtime)
    assert "capture_output" not in seen
    assert "creationflags" not in seen
    assert seen["stdout"] is not None
    assert seen["stderr"] is not None
