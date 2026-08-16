from __future__ import annotations

import io
import os
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from orion import whisper_cpp_stt as stt


def _write_wav(path: Path, sample_rate: int = 16000, channels: int = 1, *, sample_width: int = 2) -> None:
    payload = (b"\x00" * sample_width * channels) * sample_rate
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(payload)


def _bind_runtime(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[Path, Path]:
    cli = root / "whisper-cli.exe"
    model = root / "models" / stt.WHISPER_MODEL_FILENAME
    monkeypatch.setattr(stt, "stt_root", lambda: root)
    monkeypatch.setattr(stt, "download_root", lambda: root / "downloads")
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    monkeypatch.setattr(stt, "runtime_archive_path", lambda: root / "downloads" / stt.RUNTIME_ARCHIVE_NAME)
    monkeypatch.setattr(
        stt,
        "runtime_archive_part_path",
        lambda: root / "downloads" / f"{stt.RUNTIME_ARCHIVE_NAME}.part",
    )
    monkeypatch.setattr(stt, "model_part_path", lambda: root / "downloads" / f"{stt.WHISPER_MODEL_FILENAME}.part")
    return cli, model


def _complete_runtime(root: Path, cli: Path, model: Path) -> None:
    cli.parent.mkdir(parents=True, exist_ok=True)
    model.parent.mkdir(parents=True, exist_ok=True)
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    (root / stt.PORTABLE_CPU_BACKEND).write_bytes(b"cpu")
    (root / stt.RUNTIME_VERSION_MARKER).write_text(stt.WHISPER_CPP_VERSION + "\n", encoding="utf-8")


def test_locked_stt_baseline_is_whisper_186_medium_cpu() -> None:
    assert stt.WHISPER_CPP_VERSION == "v1.8.6"
    assert stt.WHISPER_MODEL_NAME == "medium"
    assert stt.WHISPER_MODEL_FILENAME == "ggml-medium.bin"
    assert stt.WHISPER_MODEL_SHA1 == "fd9727b6e1217c2f614f9b698455c4ffd82463b4"
    assert stt.PORTABLE_CPU_BACKEND == "ggml-cpu.dll"
    assert "/v1.8.6/whisper-bin-x64.zip" in stt.WHISPER_WINDOWS_X64_URL


def test_thread_budget_defaults_and_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORION_WHISPER_THREADS", raising=False)
    assert stt.configured_threads() == 4
    monkeypatch.setenv("ORION_WHISPER_THREADS", "99")
    assert stt.configured_threads() == 16
    monkeypatch.setenv("ORION_WHISPER_THREADS", "0")
    assert stt.configured_threads() == 1
    monkeypatch.setenv("ORION_WHISPER_THREADS", "bad")
    assert stt.configured_threads() == 4


def test_runtime_paths_are_persistent_under_runtime_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("ORION_WHISPER_ROOT", raising=False)
    monkeypatch.delenv("ORION_WHISPER_CLI", raising=False)
    monkeypatch.delenv("ORION_WHISPER_MODEL", raising=False)
    root = tmp_path / "stt" / "whisper.cpp"
    assert stt.stt_root() == root
    assert stt.download_root() == root / "downloads"
    assert stt.runtime_archive_part_path().name.endswith(".zip.part")
    assert stt.model_part_path() == root / "downloads" / "ggml-medium.bin.part"


def test_runtime_ready_requires_version_marker_and_generic_cpu_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli, model = _bind_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))
    cli.parent.mkdir(parents=True)
    model.parent.mkdir(parents=True)
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    assert stt.runtime_ready() is False
    (tmp_path / stt.PORTABLE_CPU_BACKEND).write_bytes(b"cpu")
    assert stt.runtime_ready() is False
    (tmp_path / stt.RUNTIME_VERSION_MARKER).write_text("v1.8.6\n", encoding="utf-8")
    assert stt.runtime_ready() is True


class _Response:
    def __init__(self, payload: bytes, *, status: int, headers: dict[str, str]) -> None:
        self._stream = io.BytesIO(payload)
        self.status = status
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_download_resumes_from_existing_part_with_http_range(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    part = tmp_path / "ggml-medium.bin.part"
    part.write_bytes(b"already-")
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["range"] = request.headers.get("Range")
        captured["timeout"] = timeout
        return _Response(b"remaining", status=206, headers={"Content-Length": "9", "Content-Range": "bytes 8-16/17"})

    monkeypatch.setattr(stt.urllib.request, "urlopen", fake_urlopen)
    events: list[tuple[str, int, int | None]] = []
    stt._download("https://example.invalid/model", part, stage="model", progress=lambda *args: events.append(args))
    assert captured["range"] == "bytes=8-"
    assert part.read_bytes() == b"already-remaining"
    assert events[0] == ("model", 8, 17)
    assert events[-1] == ("model", 17, 17)


def test_resume_refuses_server_200_and_preserves_partial_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    part = tmp_path / "ggml-medium.bin.part"
    original = b"keep-these-downloaded-bytes"
    part.write_bytes(original)
    monkeypatch.setattr(
        stt.urllib.request,
        "urlopen",
        lambda request, timeout: _Response(b"server-restarted", status=200, headers={"Content-Length": "16"}),
    )
    with pytest.raises(RuntimeError, match="did not honor the HTTP Range"):
        stt._download("https://example.invalid/model", part, stage="model")
    assert part.read_bytes() == original


def test_interrupted_download_preserves_new_bytes_for_next_attempt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FailingResponse(_Response):
        def __init__(self) -> None:
            super().__init__(b"", status=200, headers={"Content-Length": "100"})
            self.calls = 0

        def read(self, size: int = -1) -> bytes:
            self.calls += 1
            if self.calls == 1:
                return b"partial-data"
            raise OSError("network lost")

    target = tmp_path / "runtime.zip.part"
    monkeypatch.setattr(stt.urllib.request, "urlopen", lambda request, timeout: FailingResponse())
    with pytest.raises(OSError, match="network lost"):
        stt._download("https://example.invalid/runtime", target, stage="runtime")
    assert target.read_bytes() == b"partial-data"


def test_ensure_runtime_reuses_existing_ready_install_without_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli, model = _bind_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))
    _complete_runtime(tmp_path, cli, model)
    monkeypatch.setattr(stt, "_download", lambda *args, **kwargs: pytest.fail("must not download"))
    events: list[tuple[str, int, int | None]] = []
    assert stt.ensure_runtime(progress=lambda *args: events.append(args)) == (cli, model)
    assert events == [("ready", 1, 1)]


def test_ensure_runtime_installs_186_runtime_and_medium_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli, model = _bind_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))

    def fake_download(url: str, target: Path, *, stage: str, progress=None) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if stage == "runtime":
            with zipfile.ZipFile(target, "w") as package:
                package.writestr("bin/whisper-cli.exe", b"cli")
                package.writestr("bin/whisper.dll", b"dll")
                package.writestr("bin/ggml-cpu.dll", b"cpu")
                package.writestr("bin/ggml-cpu-avx2.dll", b"optimized")
        else:
            target.write_bytes(b"model")
        if progress:
            progress(stage, target.stat().st_size, target.stat().st_size)

    monkeypatch.setattr(stt, "_download", fake_download)
    monkeypatch.setattr(
        stt,
        "_hash",
        lambda path, algorithm: stt.WHISPER_WINDOWS_X64_SHA256 if algorithm == "sha256" else stt.WHISPER_MODEL_SHA1,
    )
    events: list[tuple[str, int, int | None]] = []
    assert stt.ensure_runtime(progress=lambda *args: events.append(args)) == (cli, model)
    assert cli.read_bytes() == b"cli"
    assert model.read_bytes() == b"model"
    assert (tmp_path / "ggml-cpu.dll").is_file()
    assert (tmp_path / stt.RUNTIME_VERSION_MARKER).read_text(encoding="utf-8").strip() == "v1.8.6"
    assert events[-1] == ("ready", 1, 1)


def test_runtime_checksum_failure_keeps_part_for_diagnosis(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _bind_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))

    def fake_download(url: str, target: Path, *, stage: str, progress=None) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"bad-runtime")

    monkeypatch.setattr(stt, "_download", fake_download)
    monkeypatch.setattr(stt, "_hash", lambda path, algorithm: "bad")
    with pytest.raises(RuntimeError, match="runtime checksum mismatch"):
        stt.ensure_runtime()
    assert stt.runtime_archive_part_path().read_bytes() == b"bad-runtime"


def test_recognizer_never_downloads_implicitly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "input.wav"
    _write_wav(source)
    monkeypatch.setattr(stt, "runtime_ready", lambda: False)
    with pytest.raises(RuntimeError, match="Install speech recognition from Launcher first"):
        stt.recognize_wav(source)


def test_recognizer_forces_cpu_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "input.wav"
    _write_wav(source)
    cli = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-medium.bin"
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    monkeypatch.setattr(stt, "runtime_ready", lambda: True)
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    captured: dict[str, object] = {}

    def fake_run(command: list[str]):
        captured["command"] = command
        output = Path(command[command.index("--output-file") + 1]).with_suffix(".txt")
        output.write_text("Привет как дела", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(stt, "_run_whisper", fake_run)
    assert stt.recognize_wav(source, language="ru") == "Привет как дела"
    command = captured["command"]
    assert isinstance(command, list)
    assert "--no-gpu" in command
    assert command[command.index("--processors") + 1] == "1"
    assert command[command.index("--language") + 1] == "ru"


def test_windows_backend_crash_retries_with_generic_cpu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "input.wav"
    _write_wav(source)
    cli = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-medium.bin"
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    (tmp_path / "ggml-cpu.dll").write_bytes(b"generic")
    (tmp_path / "ggml-cpu-avx2.dll").write_bytes(b"optimized")
    monkeypatch.setattr(stt, "runtime_ready", lambda: True)
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    monkeypatch.setattr(stt, "os", SimpleNamespace(name="nt", environ=os.environ))
    calls = 0

    def fake_run(command: list[str]):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(returncode=stt.WINDOWS_ILLEGAL_INSTRUCTION, stdout="", stderr="")
        output = Path(command[command.index("--output-file") + 1]).with_suffix(".txt")
        output.write_text("recovered", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(stt, "_run_whisper", fake_run)
    assert stt.recognize_wav(source) == "recovered"
    assert calls == 2
    assert not (tmp_path / "ggml-cpu-avx2.dll").exists()
    assert (tmp_path / "ggml-cpu-avx2.dll.orion-disabled").exists()
    assert (tmp_path / "ORION_PORTABLE_CPU_BACKEND.txt").is_file()


def test_audio_input_is_resampled_to_16khz_pcm16(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    target = tmp_path / "target.wav"
    _write_wav(source, sample_rate=48000, channels=2)
    stt._prepare_input_wav(source, target)
    with wave.open(str(target), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2


def test_non_pcm16_input_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad.wav"
    _write_wav(source, sample_width=1)
    with pytest.raises(RuntimeError, match="16-bit PCM"):
        stt._read_pcm16_mono_16k(source)
