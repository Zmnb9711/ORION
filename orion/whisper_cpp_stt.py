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
WHISPER_CPP_VERSION = "v1.8.6"
WHISPER_WINDOWS_X64_SHA256 = "b07ea0b1b4115a38e1a7b07debf581f0b77d999925f8acb8f39d322b0ba0a822"
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
WINDOWS_FAIL_FAST_EXCEPTION = 0xC0000409
WINDOWS_PORTABLE_RECOVERY_STATUSES = frozenset({WINDOWS_ILLEGAL_INSTRUCTION, WINDOWS_FAIL_FAST_EXCEPTION})
PORTABLE_CPU_BACKEND = "ggml-cpu.dll"
RUNTIME_VERSION_MARKER = "ORION_WHISPER_RUNTIME_VERSION.txt"
RUNTIME_ARCHIVE_NAME = f"whisper-bin-x64-{WHISPER_CPP_VERSION}.zip"
ProgressCallback = Callable[[str, int, int | None], None]


def stt_root() -> Path:
    override = os.environ.get("ORION_WHISPER_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    runtime = Path(os.environ.get("ORION_RUNTIME_DIR", "runtime")).expanduser().resolve()
    return runtime / "stt" / "whisper.cpp"


def download_root() -> Path:
    return stt_root() / "downloads"


def _packaged_root() -> Path | None:
    if getattr(sys, "frozen", False):
        path = Path(sys.executable).resolve().parent / "whisper"
        if path.is_dir():
            return path
    return None


def whisper_cli_path() -> Path:
    override = os.environ.get("ORION_WHISPER_CLI")
    if override:
        return Path(override).expanduser().resolve()
    packaged = _packaged_root()
    if packaged:
        path = packaged / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")
        if path.is_file():
            return path
    return stt_root() / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")


def whisper_model_path() -> Path:
    override = os.environ.get("ORION_WHISPER_MODEL")
    if override:
        return Path(override).expanduser().resolve()
    return stt_root() / "models" / WHISPER_MODEL_FILENAME


def runtime_archive_path() -> Path:
    return download_root() / RUNTIME_ARCHIVE_NAME


def runtime_archive_part_path() -> Path:
    return runtime_archive_path().with_suffix(runtime_archive_path().suffix + ".part")


def model_part_path() -> Path:
    return download_root() / f"{WHISPER_MODEL_FILENAME}.part"


def _windows_runtime_complete(cli: Path) -> bool:
    if os.name != "nt":
        return True
    packaged = _packaged_root()
    if packaged and cli.parent.resolve() == packaged.resolve():
        return (cli.parent / PORTABLE_CPU_BACKEND).is_file()
    marker = cli.parent / RUNTIME_VERSION_MARKER
    try:
        version = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return (cli.parent / PORTABLE_CPU_BACKEND).is_file() and version == WHISPER_CPP_VERSION


def runtime_ready() -> bool:
    cli = whisper_cli_path()
    return cli.is_file() and whisper_model_path().is_file() and _windows_runtime_complete(cli)


def configured_threads() -> int:
    try:
        value = int(os.environ.get("ORION_WHISPER_THREADS", str(DEFAULT_THREADS)))
    except ValueError:
        value = DEFAULT_THREADS
    return max(1, min(value, 16))


def _hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _response_status(response: object) -> int:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        value = getcode()
        if isinstance(value, int):
            return value
    return 200


def _content_length(response: object) -> int | None:
    headers = getattr(response, "headers", {})
    raw = headers.get("Content-Length") if hasattr(headers, "get") else None
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _validate_resume_response(response: object, offset: int) -> None:
    if offset <= 0:
        return
    status = _response_status(response)
    headers = getattr(response, "headers", {})
    content_range = headers.get("Content-Range") if hasattr(headers, "get") else None
    expected_prefix = f"bytes {offset}-"
    if status != 206 or not isinstance(content_range, str) or not content_range.startswith(expected_prefix):
        raise RuntimeError(
            "Whisper download cannot safely resume because the server did not honor the HTTP Range request. "
            "The partial download was preserved; try again later."
        )


def _download(url: str, target: Path, *, stage: str, progress: ProgressCallback | None = None) -> None:
    """Download to a persistent .part file and resume it without discarding bytes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    offset = target.stat().st_size if target.is_file() else 0
    headers = {"User-Agent": "ORION-DCS/0.2"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        _validate_resume_response(response, offset)
        remaining = _content_length(response)
        total = offset + remaining if remaining is not None else None
        mode = "ab" if offset else "wb"
        done = offset
        if progress is not None:
            progress(stage, done, total)
        with target.open(mode) as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                output.flush()
                done += len(chunk)
                if progress is not None:
                    progress(stage, done, total)


def _verified_download(
    url: str,
    part: Path,
    complete: Path,
    *,
    stage: str,
    algorithm: str,
    expected_hash: str,
    progress: ProgressCallback | None = None,
) -> Path:
    if complete.is_file() and _hash(complete, algorithm) == expected_hash:
        return complete
    _download(url, part, stage=stage, progress=progress)
    verify_stage = f"{stage}_verify"
    if progress is not None:
        progress(verify_stage, 0, None)
    actual = _hash(part, algorithm)
    if actual != expected_hash:
        raise RuntimeError(f"Whisper {stage} checksum mismatch: {actual}. Partial file was preserved for diagnosis.")
    complete.parent.mkdir(parents=True, exist_ok=True)
    part.replace(complete)
    return complete


def _install_runtime_archive(archive: Path, root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="orion-whisper-runtime-") as temp:
        extracted = Path(temp) / "runtime"
        with zipfile.ZipFile(archive) as package:
            package.extractall(extracted)
        found_cli = next(extracted.rglob("whisper-cli.exe"), None)
        if found_cli is None:
            raise RuntimeError("whisper-cli.exe was not found in the official whisper.cpp package")
        for item in found_cli.parent.iterdir():
            destination = root / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(item, destination)
    (root / RUNTIME_VERSION_MARKER).write_text(WHISPER_CPP_VERSION + "\n", encoding="utf-8")


def ensure_runtime(progress: ProgressCallback | None = None) -> tuple[Path, Path]:
    """Explicit installer/repair entry point for ORION Whisper STT."""
    cli = whisper_cli_path()
    model = whisper_model_path()
    if runtime_ready():
        if progress is not None:
            progress("ready", 1, 1)
        return cli, model
    if os.name != "nt" and not cli.is_file():
        raise RuntimeError("Automatic ORION Whisper provisioning currently supports Windows x64 only")

    root = stt_root()
    root.mkdir(parents=True, exist_ok=True)
    download_root().mkdir(parents=True, exist_ok=True)

    if not cli.is_file() or not _windows_runtime_complete(cli):
        archive = _verified_download(
            WHISPER_WINDOWS_X64_URL,
            runtime_archive_part_path(),
            runtime_archive_path(),
            stage="runtime",
            algorithm="sha256",
            expected_hash=WHISPER_WINDOWS_X64_SHA256,
            progress=progress,
        )
        _install_runtime_archive(archive, root)
        cli = whisper_cli_path()

    if not model.is_file():
        downloaded_model = _verified_download(
            WHISPER_MODEL_URL,
            model_part_path(),
            download_root() / WHISPER_MODEL_FILENAME,
            stage="model",
            algorithm="sha1",
            expected_hash=WHISPER_MODEL_SHA1,
            progress=progress,
        )
        model.parent.mkdir(parents=True, exist_ok=True)
        downloaded_model.replace(model)

    if not runtime_ready():
        raise RuntimeError("ORION Whisper runtime provisioning did not produce the required files")
    if progress is not None:
        progress("ready", 1, 1)
    return whisper_cli_path(), model


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
            frame = samples[index:index + channels]
            mono.append(int(sum(frame) / len(frame)))
        samples = mono
    if sample_rate != TARGET_SAMPLE_RATE:
        if sample_rate <= 0:
            raise RuntimeError(f"Invalid WAV sample rate: {sample_rate}")
        count = max(1, int(round(len(samples) * TARGET_SAMPLE_RATE / sample_rate)))
        resampled = array("h")
        if len(samples) == 1:
            resampled.extend([samples[0]] * count)
        elif samples:
            scale = (len(samples) - 1) / max(1, count - 1)
            for target_index in range(count):
                position = target_index * scale
                left = int(position)
                right = min(left + 1, len(samples) - 1)
                fraction = position - left
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


def _is_windows_portable_recovery_status(returncode: int) -> bool:
    return os.name == "nt" and _windows_status(returncode) in WINDOWS_PORTABLE_RECOVERY_STATUSES


def _portable_backend_available(root: Path) -> bool:
    return (root / PORTABLE_CPU_BACKEND).is_file()


def _force_portable_cpu_backend(root: Path, *, trigger_status: int | None = None) -> list[Path]:
    portable = root / PORTABLE_CPU_BACKEND
    if not portable.is_file():
        return []
    disabled: list[Path] = []
    for candidate in sorted(root.glob("ggml-cpu-*.dll")):
        destination = candidate.with_suffix(candidate.suffix + ".orion-disabled")
        destination.unlink(missing_ok=True)
        candidate.replace(destination)
        disabled.append(destination)
    status = f"0x{trigger_status:08X}" if trigger_status is not None else "unknown"
    (root / "ORION_PORTABLE_CPU_BACKEND.txt").write_text(
        f"ORION is using the pinned generic ggml-cpu.dll backend after a Windows whisper.cpp backend crash ({status}).\n",
        encoding="utf-8",
    )
    return disabled


def _run_whisper(command: list[str]) -> subprocess.CompletedProcess[str]:
    # whisper.cpp may emit localized/native-library diagnostics that are not
    # valid UTF-8 on Windows. The transcript file remains authoritative, so
    # console diagnostics must never crash STT decoding.
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _failure_detail(completed: subprocess.CompletedProcess[str], *, recovered: bool = False) -> str:
    detail = completed.stderr.strip() or completed.stdout.strip() or "no process output"
    status = _windows_status(completed.returncode) if os.name == "nt" else completed.returncode
    rendered = f"0x{status:08X}" if os.name == "nt" else str(status)
    prefix = "generic CPU retry failed" if recovered else "process failed"
    return f"{prefix}; exit={completed.returncode} status={rendered}; {detail}"


def recognize_wav(path: Path | str, *, language: str = "auto") -> str:
    if not runtime_ready():
        raise RuntimeError("Whisper medium is not prepared. Install speech recognition from Launcher first.")
    cli = whisper_cli_path()
    model = whisper_model_path()
    with tempfile.TemporaryDirectory(prefix="orion-whisper-") as temp:
        directory = Path(temp)
        prepared = directory / "input-16k.wav"
        output = directory / "transcript"
        _prepare_input_wav(Path(path), prepared)
        command = [
            str(cli),
            "--model", str(model),
            "--file", str(prepared),
            "--threads", str(configured_threads()),
            "--processors", "1",
            "--no-gpu",
            "--no-timestamps",
            "--no-prints",
            "--output-txt",
            "--output-file", str(output),
            "--language", language,
        ]
        completed = _run_whisper(command)
        if completed.returncode != 0 and _is_windows_portable_recovery_status(completed.returncode):
            root = cli.parent
            status = _windows_status(completed.returncode)
            if _portable_backend_available(root):
                _force_portable_cpu_backend(root, trigger_status=status)
                completed = _run_whisper(command)
                if completed.returncode != 0:
                    raise RuntimeError(f"Whisper STT failed: {_failure_detail(completed, recovered=True)}")
            else:
                raise RuntimeError(
                    f"Whisper STT failed with recoverable Windows backend status 0x{status:08X}, "
                    "and the pinned ggml-cpu.dll backend is unavailable"
                )
        elif completed.returncode != 0:
            raise RuntimeError(f"Whisper STT failed: {_failure_detail(completed)}")
        transcript = output.with_suffix(".txt")
        text = transcript.read_text(encoding="utf-8", errors="replace").strip() if transcript.is_file() else completed.stdout.strip()
        return " ".join(text.split())
