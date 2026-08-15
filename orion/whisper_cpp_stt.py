from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from contextlib import contextmanager
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
PORTABLE_CPU_BACKEND = "ggml-cpu.dll"
RUNTIME_VERSION_MARKER = "ORION_WHISPER_RUNTIME_VERSION.txt"
ProgressCallback = Callable[[str, int, int | None], None]
_DLL_SEARCH_LOCK = threading.Lock()


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
    marker = cli.parent / RUNTIME_VERSION_MARKER
    try:
        installed_version = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return (cli.parent / PORTABLE_CPU_BACKEND).is_file() and installed_version == WHISPER_CPP_VERSION


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
    """Install or repair the pinned CPU-only whisper.cpp runtime and medium model."""
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
        if not cli.is_file() or not _windows_runtime_complete(cli):
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
            (root / RUNTIME_VERSION_MARKER).write_text(WHISPER_CPP_VERSION + "\n", encoding="utf-8")

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


def _hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is None:
        return None
    startupinfo = startupinfo_type()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return startupinfo


def _sanitized_child_env() -> dict[str, str]:
    """Return an environment safe for external native programs launched by frozen Core."""
    env = os.environ.copy()
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return env

    bundle_dir_raw = getattr(sys, "_MEIPASS", None)
    if not bundle_dir_raw:
        return env
    bundle_dir = Path(bundle_dir_raw).resolve()
    cleaned: list[str] = []
    for entry in env.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve()
            if resolved == bundle_dir or bundle_dir in resolved.parents:
                continue
        except OSError:
            pass
        cleaned.append(entry)
    env["PATH"] = os.pathsep.join(cleaned)
    return env


@contextmanager
def _external_program_dll_scope():
    """Use the normal Windows DLL search path only while creating an external process."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        yield
        return

    bundle_dir = getattr(sys, "_MEIPASS", None)
    if not bundle_dir:
        yield
        return

    kernel32 = ctypes.windll.kernel32
    with _DLL_SEARCH_LOCK:
        if not kernel32.SetDllDirectoryW(None):
            raise OSError(ctypes.get_last_error(), "SetDllDirectoryW(NULL) failed before Whisper launch")
        try:
            yield
        finally:
            if not kernel32.SetDllDirectoryW(str(bundle_dir)):
                raise OSError(ctypes.get_last_error(), "Failed to restore PyInstaller DLL search path")


def _spawn_whisper(
    command: list[str],
    *,
    cwd: Path,
    stdout_handle,
    stderr_handle,
) -> int:
    """Create whisper-cli under a sanitized DLL search path, then restore Core immediately."""
    with _external_program_dll_scope():
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=_sanitized_child_env(),
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            startupinfo=_hidden_startupinfo(),
        )
    return process.wait()


def recognize_wav(path: Path, *, language: str = "auto") -> str:
    """Recognize the original captured WAV using the single canonical Whisper path."""
    if not runtime_ready():
        raise RuntimeError("Whisper medium is not prepared. Install speech recognition from Launcher first.")

    cli = whisper_cli_path()
    model = whisper_model_path()
    source = Path(path).resolve()
    if not source.is_file():
        raise RuntimeError(f"Whisper input WAV does not exist: {source}")

    with tempfile.TemporaryDirectory(prefix="orion-whisper-result-") as tmp:
        tmp_dir = Path(tmp)
        output_base = tmp_dir / "transcript"
        stdout_path = tmp_dir / "whisper-stdout.log"
        stderr_path = tmp_dir / "whisper-stderr.log"
        command = [
            str(cli),
            "--model",
            str(model),
            "--file",
            str(source),
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
        with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_handle, stderr_path.open(
            "w", encoding="utf-8", errors="replace"
        ) as stderr_handle:
            returncode = _spawn_whisper(
                command,
                cwd=cli.parent,
                stdout_handle=stdout_handle,
                stderr_handle=stderr_handle,
            )

        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        if returncode != 0:
            detail = stderr_text or stdout_text or "no process output"
            status = returncode & 0xFFFFFFFF
            raise RuntimeError(f"Whisper STT failed: exit={returncode} status=0x{status:08X}; {detail}")

        transcript_path = output_base.with_suffix(".txt")
        text = (
            transcript_path.read_text(encoding="utf-8", errors="replace").strip()
            if transcript_path.is_file()
            else stdout_text
        )
        return " ".join(text.split())
