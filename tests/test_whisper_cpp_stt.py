from __future__ import annotations

import os
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from orion import whisper_cpp_stt as stt


def _write_wav(
    path: Path,
    sample_rate: int = 48000,
    channels: int = 1,
    *,
    sample_width: int = 2,
    frames: int | None = None,
) -> None:
    frame_count = frames if frames is not None else sample_rate
    payload = (b"\x00" * sample_width * channels) * frame_count
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(payload)


def _bind_runtime(monkeypatch: pytest.MonkeyPatch, cli: Path, model: Path) -> None:
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)


def test_medium_model_is_canonical_default() -> None:
    assert stt.WHISPER_MODEL_NAME == "medium"
    assert stt.WHISPER_MODEL_FILENAME == "ggml-medium.bin"
    assert stt.WHISPER_MODEL_SHA1 == "fd9727b6e1217c2f614f9b698455c4ffd82463b4"
    assert stt.WHISPER_CPP_VERSION == "v1.9.2"
    assert "whisper-bin-x64.zip" in stt.WHISPER_WINDOWS_X64_URL


def test_thread_budget_defaults_clamps_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORION_WHISPER_THREADS", raising=False)
    assert stt.configured_threads() == 4
    monkeypatch.setenv("ORION_WHISPER_THREADS", "99")
    assert stt.configured_threads() == 16
    monkeypatch.setenv("ORION_WHISPER_THREADS", "0")
    assert stt.configured_threads() == 1
    monkeypatch.setenv("ORION_WHISPER_THREADS", "invalid")
    assert stt.configured_threads() == 4


def test_runtime_paths_use_runtime_dir_and_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("ORION_WHISPER_ROOT", raising=False)
    monkeypatch.delenv("ORION_WHISPER_CLI", raising=False)
    monkeypatch.delenv("ORION_WHISPER_MODEL", raising=False)
    root = tmp_path / "stt" / "whisper.cpp"
    assert stt.stt_root() == root
    assert stt.whisper_model_path() == root / "models" / "ggml-medium.bin"

    custom_root = tmp_path / "custom-root"
    custom_cli = tmp_path / "custom-cli.exe"
    custom_model = tmp_path / "custom-model.bin"
    monkeypatch.setenv("ORION_WHISPER_ROOT", str(custom_root))
    monkeypatch.setenv("ORION_WHISPER_CLI", str(custom_cli))
    monkeypatch.setenv("ORION_WHISPER_MODEL", str(custom_model))
    assert stt.stt_root() == custom_root.resolve()
    assert stt.whisper_cli_path() == custom_cli.resolve()
    assert stt.whisper_model_path() == custom_model.resolve()


def test_runtime_ready_requires_cli_and_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cli = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-medium.bin"
    _bind_runtime(monkeypatch, cli, model)
    assert stt.runtime_ready() is False
    cli.write_bytes(b"cli")
    assert stt.runtime_ready() is False
    model.write_bytes(b"model")
    assert stt.runtime_ready() is True


def test_hash_reads_file(tmp_path: Path) -> None:
    target = tmp_path / "payload.bin"
    target.write_bytes(b"orion")
    assert stt._hash(target, "sha1") == "091e17a9b3e16e0ce475fc93693b3549fb1cc7e8"


def test_ensure_runtime_returns_existing_payload_and_reports_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cli = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-medium.bin"
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    _bind_runtime(monkeypatch, cli, model)
    events: list[tuple[str, int, int | None]] = []
    assert stt.ensure_runtime(progress=lambda *args: events.append(args)) == (cli, model)
    assert events == [("ready", 1, 1)]


def test_ensure_runtime_rejects_automatic_non_windows_provisioning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = tmp_path / "whisper-cli"
    model = tmp_path / "ggml-medium.bin"
    _bind_runtime(monkeypatch, cli, model)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="posix", environ=os.environ))
    with pytest.raises(RuntimeError, match="Windows x64 only"):
        stt.ensure_runtime()


def test_ensure_runtime_provisions_cpu_runtime_and_medium_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "runtime"
    cli = root / "whisper-cli.exe"
    model = root / "models" / "ggml-medium.bin"
    monkeypatch.setattr(stt, "stt_root", lambda: root)
    _bind_runtime(monkeypatch, cli, model)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))

    def fake_download(url: str, target: Path, *, stage: str, progress=None) -> None:
        if target.suffix == ".zip":
            with zipfile.ZipFile(target, "w") as package:
                package.writestr("bin/whisper-cli.exe", b"cli")
                package.writestr("bin/whisper.dll", b"dll")
                package.writestr("bin/ggml-cpu-x64.dll", b"x64")
        else:
            target.write_bytes(b"model")
        if progress is not None:
            progress(stage, target.stat().st_size, target.stat().st_size)

    def fake_hash(path: Path, algorithm: str) -> str:
        return stt.WHISPER_WINDOWS_X64_SHA256 if algorithm == "sha256" else stt.WHISPER_MODEL_SHA1

    events: list[tuple[str, int, int | None]] = []
    monkeypatch.setattr(stt, "_download", fake_download)
    monkeypatch.setattr(stt, "_hash", fake_hash)
    assert stt.ensure_runtime(progress=lambda *args: events.append(args)) == (cli, model)
    assert cli.read_bytes() == b"cli"
    assert (root / "whisper.dll").read_bytes() == b"dll"
    assert (root / "ggml-cpu-x64.dll").read_bytes() == b"x64"
    assert model.read_bytes() == b"model"
    assert events[-1] == ("ready", 1, 1)
    assert any(stage == "runtime" for stage, _, _ in events)
    assert any(stage == "model" for stage, _, _ in events)


def test_ensure_runtime_rejects_runtime_checksum_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "runtime"
    cli = root / "whisper-cli.exe"
    model = root / "models" / "ggml-medium.bin"
    monkeypatch.setattr(stt, "stt_root", lambda: root)
    _bind_runtime(monkeypatch, cli, model)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))
    monkeypatch.setattr(stt, "_download", lambda url, target, **kwargs: target.write_bytes(b"bad"))
    monkeypatch.setattr(stt, "_hash", lambda path, algorithm: "bad-checksum")
    with pytest.raises(RuntimeError, match="runtime checksum mismatch"):
        stt.ensure_runtime()


def test_ensure_runtime_rejects_archive_without_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "runtime"
    cli = root / "whisper-cli.exe"
    model = root / "models" / "ggml-medium.bin"
    monkeypatch.setattr(stt, "stt_root", lambda: root)
    _bind_runtime(monkeypatch, cli, model)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))

    def fake_download(url: str, target: Path, **kwargs) -> None:
        with zipfile.ZipFile(target, "w") as package:
            package.writestr("bin/readme.txt", "missing cli")

    monkeypatch.setattr(stt, "_download", fake_download)
    monkeypatch.setattr(stt, "_hash", lambda path, algorithm: stt.WHISPER_WINDOWS_X64_SHA256)
    with pytest.raises(RuntimeError, match="whisper-cli.exe was not found"):
        stt.ensure_runtime()


def test_ensure_runtime_rejects_medium_model_checksum_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    cli = root / "whisper-cli.exe"
    model = root / "models" / "ggml-medium.bin"
    cli.write_bytes(b"cli")
    monkeypatch.setattr(stt, "stt_root", lambda: root)
    _bind_runtime(monkeypatch, cli, model)
    monkeypatch.setattr(stt, "_download", lambda url, target, **kwargs: target.write_bytes(b"bad-model"))
    monkeypatch.setattr(stt, "_hash", lambda path, algorithm: "bad-model-checksum")
    with pytest.raises(RuntimeError, match="medium model checksum mismatch"):
        stt.ensure_runtime()


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


def test_prepare_input_downmixes_stereo(tmp_path: Path) -> None:
    source = tmp_path / "stereo.wav"
    target = tmp_path / "mono.wav"
    _write_wav(source, sample_rate=16000, channels=2, frames=100)
    stt._prepare_input_wav(source, target)
    with wave.open(str(target), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getnframes() == 100


def test_prepare_input_handles_single_sample_resampling(tmp_path: Path) -> None:
    source = tmp_path / "single.wav"
    target = tmp_path / "single-16k.wav"
    _write_wav(source, sample_rate=8000, frames=1)
    stt._prepare_input_wav(source, target)
    with wave.open(str(target), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 2


def test_prepare_input_rejects_non_pcm16(tmp_path: Path) -> None:
    source = tmp_path / "pcm8.wav"
    _write_wav(source, sample_rate=16000, sample_width=1)
    with pytest.raises(RuntimeError, match="16-bit PCM"):
        stt._read_pcm16_mono_16k(source)


def test_recognizer_refuses_to_download_implicitly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    _write_wav(source, sample_rate=16000)
    monkeypatch.setattr(stt, "runtime_ready", lambda: False)
    with pytest.raises(RuntimeError, match="not prepared"):
        stt.recognize_wav(source)


def test_recognizer_forces_cpu_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    cli = tmp_path / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")
    model = tmp_path / "ggml-medium.bin"
    _write_wav(source, sample_rate=16000)
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    _bind_runtime(monkeypatch, cli, model)
    monkeypatch.setattr(stt, "runtime_ready", lambda: True)

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
    assert command[command.index("--processors") + 1] == "1"
    assert command[command.index("--language") + 1] == "ru"
    assert text == "Привет, как дела?"


def test_recognizer_reads_generated_transcript_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    cli = tmp_path / "whisper-cli"
    model = tmp_path / "ggml-medium.bin"
    _write_wav(source, sample_rate=16000)
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    _bind_runtime(monkeypatch, cli, model)
    monkeypatch.setattr(stt, "runtime_ready", lambda: True)

    def fake_run(command, **kwargs):
        output_base = Path(command[command.index("--output-file") + 1])
        output_base.with_suffix(".txt").write_text("  Привет   как дела  ", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ignored", stderr="")

    monkeypatch.setattr(stt.subprocess, "run", fake_run)
    assert stt.recognize_wav(source, language="auto") == "Привет как дела"


def test_recognizer_reports_cli_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    cli = tmp_path / "whisper-cli"
    model = tmp_path / "ggml-medium.bin"
    _write_wav(source, sample_rate=16000)
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    _bind_runtime(monkeypatch, cli, model)
    monkeypatch.setattr(stt, "runtime_ready", lambda: True)
    monkeypatch.setattr(
        stt.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="", stderr="decoder failed"),
    )
    with pytest.raises(RuntimeError, match="decoder failed"):
        stt.recognize_wav(source)
