from __future__ import annotations

import os
import wave
from pathlib import Path
from types import SimpleNamespace

from orion import whisper_cpp_stt as stt


def _wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)


def test_recovery_statuses_include_illegal_instruction_and_fail_fast(monkeypatch) -> None:
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))
    assert stt._is_windows_portable_recovery_status(-1073741795) is True  # 0xC000001D
    assert stt._is_windows_portable_recovery_status(-1073740791) is True  # 0xC0000409
    assert stt._is_windows_portable_recovery_status(2) is False


def test_fail_fast_retries_with_portable_backend(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    _wav(source)
    root = tmp_path / "runtime"
    root.mkdir()
    cli = root / "whisper-cli.exe"
    model = root / "ggml-medium.bin"
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    (root / stt.PORTABLE_CPU_BACKEND).write_bytes(b"x64")
    (root / "ggml-cpu-haswell.dll").write_bytes(b"haswell")

    monkeypatch.setattr(stt, "runtime_ready", lambda: True)
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))

    calls = []

    def fake_run(command):
        calls.append(command)
        if len(calls) == 1:
            return SimpleNamespace(returncode=-1073740791, stdout="", stderr="load_backend: loaded CPU backend")
        output_base = Path(command[command.index("--output-file") + 1])
        output_base.with_suffix(".txt").write_text("Привет, как дела?", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(stt, "_run_whisper", fake_run)

    assert stt.recognize_wav(source, language="ru") == "Привет, как дела?"
    assert len(calls) == 2
    assert not (root / "ggml-cpu-haswell.dll").exists()
    assert (root / "ggml-cpu-haswell.dll.orion-disabled").is_file()
    assert (root / stt.PORTABLE_CPU_BACKEND).is_file()
    marker = (root / "ORION_PORTABLE_CPU_BACKEND.txt").read_text(encoding="utf-8")
    assert "0xC0000409" in marker
