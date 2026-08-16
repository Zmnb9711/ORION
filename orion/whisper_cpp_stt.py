from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
import wave
import zipfile
from array import array
from pathlib import Path
from typing import Callable

WHISPER_MODEL_NAME = "medium"
WHISPER_MODEL_FILENAME = "ggml-medium.bin"
WHISPER_MODEL_SHA1 = "fd9727b6e1217c2f614f9b698455c4ffd82463b4"
WHISPER_CPP_VERSION = "v1.9.2"
WHISPER_WINDOWS_X64_URL = (
    "https://github.com/ggml-org/whisper.cpp/releases/download/"
    f"{WHISPER_CPP_VERSION}/whisper-bin-x64.zip"
)
WHISPER_WINDOWS_X64_SHA256 = "49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a"
WHISPER_MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
    f"{WHISPER_MODEL_FILENAME}"
)
PORTABLE_CPU_BACKEND = "ggml-cpu-x64.dll"

ProgressCallback = Callable[[str, int, int | None], None]


def configured_threads() -> int:
    raw = os.environ.get("ORION_WHISPER_THREADS", "4")
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(1, min(value, 16))


def stt_root() -> Path:
    override = os.environ.get("ORION_WHISPER_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    runtime = Path(os.environ.get("ORION_RUNTIME_DIR", Path.cwd() / "runtime")).expanduser().resolve()
    return runtime / "stt" / "whisper.cpp"


def whisper_cli_path() -> Path:
    override = os.environ.get("ORION_WHISPER_CLI")
    if override:
        return Path(override).expanduser().resolve()
    return stt_root() / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")


def whisper_model_path() -> Path:
    override = os.environ.get("ORION_WHISPER_MODEL")
    if override:
        return Path(override).expanduser().resolve()
    return stt_root() / "models" / WHISPER_MODEL_FILENAME


def runtime_ready() -> bool:
    cli = whisper_cli_path()
    model = whisper_model_path()
    if not cli.is_file() or not model.is_file():
        return False
    if os.name == "nt" and not (cli.parent / PORTABLE_CPU_BACKEND).is_file():
        return False
    return True


def _hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path, *, stage: str, progress: ProgressCallback | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as handle:
        total_header = response.headers.get("Content-Length")
        total = int(total_header) if total_header and total_header.isdigit() else None
        done = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(stage, done, total)


def ensure_runtime(progress: ProgressCallback | None = None) -> tuple[Path, Path]:
    cli = whisper_cli_path()
    model = whisper_model_path()
    if runtime_ready():
        if progress is not None:
            progress("ready", 1, 1)
        return cli, model
    if os.name != "nt":
        raise RuntimeError("Automatic Whisper provisioning is supported on Windows x64 only")

    root = stt_root()
    root.mkdir(parents=True, exist_ok=True)
    model.parent.mkdir(parents=True, exist_ok=True)

    if not cli.is_file() or not (cli.parent / PORTABLE_CPU_BACKEND).is_file():
        with tempfile.TemporaryDirectory(prefix="orion-whisper-runtime-") as tmp:
            archive = Path(tmp) / "whisper-bin-x64.zip"
            _download(WHISPER_WINDOWS_X64_URL, archive, stage="runtime", progress=progress)
            if _hash(archive, "sha256") != WHISPER_WINDOWS_X64_SHA256:
                raise RuntimeError("Whisper runtime checksum mismatch")
            extracted = Path(tmp) / "extracted"
            with zipfile.ZipFile(archive) as package:
                package.extractall(extracted)
            found_cli = next(extracted.rglob("whisper-cli.exe"), None)
            if found_cli is None:
                raise RuntimeError("whisper-cli.exe was not found in Whisper runtime archive")
            source_dir = found_cli.parent
            for item in source_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, root / item.name)

    if not model.is_file():
        with tempfile.TemporaryDirectory(prefix="orion-whisper-model-") as tmp:
            downloaded = Path(tmp) / WHISPER_MODEL_FILENAME
            _download(WHISPER_MODEL_URL, downloaded, stage="model", progress=progress)
            if _hash(downloaded, "sha1") != WHISPER_MODEL_SHA1:
                raise RuntimeError("Whisper medium model checksum mismatch")
            shutil.copy2(downloaded, model)

    if not runtime_ready():
        raise RuntimeError("Whisper runtime is incomplete after provisioning")
    if progress is not None:
        progress("ready", 1, 1)
    return cli, model


def _read_pcm16_mono_16k(path: Path) -> array:
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise RuntimeError("Whisper input must be 16-bit PCM WAV")
        channels = wav.getnchannels()
        rate = wav.getframerate()
        frames = wav.getnframes()
        samples = array("h")
        samples.frombytes(wav.readframes(frames))
    if channels > 1:
        mono = array("h")
        for index in range(0, len(samples), channels):
            frame = samples[index:index + channels]
            mono.append(int(sum(frame) / len(frame)))
        samples = mono
    if rate == 16000:
        return samples
    if not samples:
        return samples
    target_count = max(1, round(len(samples) * 16000 / rate))
    resampled = array("h")
    for index in range(target_count):
        source = min(len(samples) - 1, int(index * rate / 16000))
        resampled.append(samples[source])
    return resampled


def _prepare_input_wav(source: Path, target: Path) -> None:
    samples = _read_pcm16_mono_16k(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(samples.tobytes())


def _normalize_transcript(text: str) -> str:
    return " ".join(text.strip().split())


def recognize_wav(source: Path | str, language: str = "auto") -> str:
    if not runtime_ready():
        raise RuntimeError("Whisper runtime is not prepared")
    source_path = Path(source)
    cli = whisper_cli_path()
    model = whisper_model_path()
    with tempfile.TemporaryDirectory(prefix="orion-whisper-input-") as tmp:
        prepared = Path(tmp) / "input-16k.wav"
        output_base = Path(tmp) / "transcript"
        _prepare_input_wav(source_path, prepared)
        command = [
            str(cli),
            "--model", str(model),
            "--file", str(prepared),
            "--threads", str(configured_threads()),
            "--processors", "1",
            "--no-gpu",
            "--output-txt",
            "--output-file", str(output_base),
        ]
        if language and language != "auto":
            command.extend(["--language", language])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Whisper recognition failed")
        transcript_path = output_base.with_suffix(".txt")
        text = transcript_path.read_text(encoding="utf-8") if transcript_path.is_file() else completed.stdout
        return _normalize_transcript(text)
