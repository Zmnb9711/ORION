from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import wave
import zipfile
from array import array
from collections.abc import Callable
from pathlib import Path

WHISPER_MODEL_NAME = "medium"
WHISPER_MODEL_FILENAME = "ggml-medium.bin"
WHISPER_MODEL_SHA1 = "fd9727b6e1217c2f614f9b698455c4ffd82463b4"
WHISPER_CPP_VERSION = "v1.9.2"
WHISPER_WINDOWS_X64_SHA256 = "49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a"
WHISPER_WINDOWS_X64_URL = (
    "https://github.com/ggml-org/whisper.cpp/releases/download/"
    f"{WHISPER_CPP_VERSION}/whisper-bin-x64.zip"
)
WHISPER_MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
    f"{WHISPER_MODEL_FILENAME}?download=true"
)
DEFAULT_THREADS = 4
TARGET_SAMPLE_RATE = 16000
WINDOWS_ILLEGAL_INSTRUCTION = 0xC000001D
PORTABLE_CPU_BACKEND = "ggml-cpu-x64.dll"
ProgressCallback = Callable[[str, int, int | None], None]


def stt_root() -> Path:
    override = os.environ.get("ORION_WHISPER_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    runtime = Path(os.environ.get("ORION_RUNTIME_DIR", "runtime"))
    return runtime / "stt" / "whisper.cpp"


def whisper_cli_path() -> Path:
    override = os.environ.get("ORION_WHISPER_CLI")
    if override:
        return Path(override).expanduser().resolve()
    name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    return stt_root() / name


def whisper_model_path() -> Path:
    override = os.environ.get("ORION_WHISPER_MODEL")
    if override:
        return Path(override).expanduser().resolve()
    return stt_root() / "models" / WHISPER_MODEL_FILENAME


def _windows_runtime_complete(cli: Path) -> bool:
    if os.name != "nt":
        return True
    return (cli.parent / PORTABLE_CPU_BACKEND).is_file()


def runtime_ready() -> bool:
    cli = whisper_cli_path()
    return cli.is_file() and whisper_model_path().is_file() and _windows_runtime_complete(cli)


def configured_threads() -> int:
    raw = os.environ.get("ORION_WHISPER_THREADS", str(DEFAULT_THREADS))
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_THREADS
    return max(1, min(value, 16))


def _hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path, *, stage: str, progress: ProgressCallback | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ORION-DCS/0.2"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
        raw_total = response.headers.get("Content-Length")
        try:
            total = int(raw_total) if raw_total else None
        except ValueError:
            total = None
        downloaded = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)
            if progress is not None:
                progress(stage, downloaded, total)


def ensure_runtime(progress: ProgressCallback | None = None) -> tuple[Path, Path]:
    """Install or repair pinned CPU-only whisper.cpp and multilingual medium model."""
    cli = whisper_cli_path()
    model = whisper_model_path()
    if cli.is_file() and model.is_file() and _windows_runtime_complete(cli):
        if progress is not None:
            progress("ready", 1, 1)
        return cli, model
    if os.name != "nt" and not cli.is_file():
        raise RuntimeError("Automatic ORION Whisper provisioning currently supports Windows x64 only")

    root = stt_root()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="orion-whisper-install-") as tmp:
        tmp_dir = Path(tmp)
        runtime_needs_repair = not cli.is_file() or not _windows_runtime_complete(cli)
        if runtime_needs_repair:
            archive = tmp_dir / "whisper-bin-x64.zip"
            _download(WHISPER_WINDOWS_X64_URL, archive, stage="runtime", progress=progress)
            if progress is not None:
                progress("runtime_verify", 0, None)
            actual = _hash(archive, "sha256")
            if actual != WHISPER_WINDOWS_X64_SHA256:
                raise RuntimeError(f"Whisper runtime checksum mismatch: {actual}")
            extracted = tmp_dir / "runtime"
            with zipfile.ZipFile(archive) as package:
                package.extractall(extracted)
            found = next(extracted.rglob("whisper-cli.exe"), None)
            if found is None:
                raise RuntimeError("whisper-cli.exe was not found in the official whisper.cpp package")
            for item in found.parent.iterdir():
                destination = root / item.name
                if item.is_dir():
                    shutil.copytree(item, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, destination)

        if not model.is_file():
            temporary_model = tmp_dir / WHISPER_MODEL_FILENAME
            _download(WHISPER_MODEL_URL, temporary_model, stage="model", progress=progress)
            if progress is not None:
                progress("model_verify", 0, None)
            actual = _hash(temporary_model, "sha1")
            if actual != WHISPER_MODEL_SHA1:
                raise RuntimeError(f"Whisper medium model checksum mismatch: {actual}")
            model.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(temporary_model, model)

    if not runtime_ready():
        raise RuntimeError("ORION Whisper runtime provisioning did not produce the required files")
    if progress is not None:
        progress("ready", 1, 1)
    return cli, model


def _read_pcm16_mono_16k(source: Path) -> bytes:
    with wave.open(str(source), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise RuntimeError(f"Whisper input must be 16-bit PCM; got sample width {sample_width}")
    if channels < 1:
        raise RuntimeError("Whisper input WAV has no audio channels")

    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()

    if channels > 1:
        mono = array("h")
        for index in range(0, len(samples), channels):
            frame = samples[index : index + channels]
            mono.append(int(sum(frame) / len(frame)))
        samples = mono

    if sample_rate != TARGET_SAMPLE_RATE:
        if sample_rate <= 0:
            raise RuntimeError(f"Invalid WAV sample rate: {sample_rate}")
        target_count = max(1, int(round(len(samples) * TARGET_SAMPLE_RATE / sample_rate)))
        resampled = array("h")
        if len(samples) == 1:
            resampled.extend([samples[0]] * target_count)
        else:
            scale = (len(samples) - 1) / max(1, target_count - 1)
            for target_index in range(target_count):
                source_pos = target_index * scale
                left = int(source_pos)
                right = min(left + 1, len(samples) - 1)
                fraction = source_pos - left
                value = round(samples[left] + (samples[right] - samples[left]) * fraction)
                resampled.append(max(-32768, min(32767, int(value))))
        samples = resampled

    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def _prepare_input_wav(source: Path, target: Path) -> None:
    pcm = _read_pcm16_mono_16k(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(TARGET_SAMPLE_RATE)
        wav.writeframes(pcm)


def _windows_status(returncode: int) -> int:
    return returncode & 0xFFFFFFFF


def _is_windows_illegal_instruction(returncode: int) -> bool:
    return os.name == "nt" and _windows_status(returncode) == WINDOWS_ILLEGAL_INSTRUCTION


def _portable_backend_available(root: Path) -> bool:
    return (root / PORTABLE_CPU_BACKEND).is_file()


def _force_portable_cpu_backend(root: Path) -> list[Path]:
    """Disable optimized CPU DLLs so ggml falls back to the generic x64 backend.

    Official whisper.cpp Windows releases are built with GGML_CPU_ALL_VARIANTS.
    On a machine where the selected optimized backend terminates with Windows
    STATUS_ILLEGAL_INSTRUCTION, preserving only ggml-cpu-x64.dll gives ORION a
    conservative CPU path without touching the Whisper model.
    """
    portable = root / PORTABLE_CPU_BACKEND
    if not portable.is_file():
        return []
    disabled: list[Path] = []
    for candidate in sorted(root.glob("ggml-cpu-*.dll")):
        if candidate.name.lower() == PORTABLE_CPU_BACKEND:
            continue
        destination = candidate.with_suffix(candidate.suffix + ".orion-disabled")
        if destination.exists():
            destination.unlink()
        candidate.replace(destination)
        disabled.append(destination)
    marker = root / "ORION_PORTABLE_CPU_BACKEND.txt"
    marker.write_text(
        "ORION disabled optimized ggml CPU backends after STATUS_ILLEGAL_INSTRUCTION; "
        "ggml-cpu-x64.dll is used for compatibility.\n",
        encoding="utf-8",
    )
    return disabled


def _run_whisper(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _failure_detail(completed: subprocess.CompletedProcess[str], *, recovered: bool = False) -> str:
    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    detail = stderr or stdout or "no process output"
    status = _windows_status(completed.returncode) if os.name == "nt" else completed.returncode
    status_text = f"0x{status:08X}" if os.name == "nt" else str(status)
    prefix = "portable CPU retry failed" if recovered else "process failed"
    return f"{prefix}; exit={completed.returncode} status={status_text}; {detail}"


def recognize_wav(path: Path, *, language: str = "auto") -> str:
    if not runtime_ready():
        raise RuntimeError("Whisper medium is not prepared. Install speech recognition from Launcher first.")
    cli = whisper_cli_path()
    model = whisper_model_path()
    with tempfile.TemporaryDirectory(prefix="orion-whisper-") as tmp:
        tmp_dir = Path(tmp)
        prepared = tmp_dir / "input-16k.wav"
        output_base = tmp_dir / "transcript"
        _prepare_input_wav(path, prepared)

        command = [
            str(cli),
            "--model",
            str(model),
            "--file",
            str(prepared),
            "--threads",
            str(configured_threads()),
            "--processors",
            "1",
            "--no-gpu",
            "--no-timestamps",
            "--no-prints",
            "--output-txt",
            "--output-file",
            str(output_base),
            "--language",
            language,
        ]
        completed = _run_whisper(command)
        if completed.returncode != 0 and _is_windows_illegal_instruction(completed.returncode):
            root = cli.parent
            if _portable_backend_available(root):
                _force_portable_cpu_backend(root)
                completed = _run_whisper(command)
                if completed.returncode != 0:
                    raise RuntimeError(f"Whisper STT failed: {_failure_detail(completed, recovered=True)}")
            else:
                raise RuntimeError(
                    "Whisper STT failed with Windows STATUS_ILLEGAL_INSTRUCTION (0xC000001D), "
                    "and the portable ggml-cpu-x64.dll backend is unavailable"
                )
        elif completed.returncode != 0:
            raise RuntimeError(f"Whisper STT failed: {_failure_detail(completed)}")

        transcript_path = output_base.with_suffix(".txt")
        if transcript_path.is_file():
            text = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
        else:
            text = completed.stdout.strip()
        return " ".join(text.split())
