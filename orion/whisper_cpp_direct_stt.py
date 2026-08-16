from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from orion.whisper_cpp_stt import (
    _failure_detail,
    _force_portable_cpu_backend,
    _is_windows_portable_recovery_status,
    _portable_backend_available,
    _windows_status,
    configured_threads,
    runtime_ready,
    whisper_cli_path,
    whisper_model_path,
)


def _run_direct(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run whisper.cpp exactly like the PR #104 field-validated Windows command."""
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def recognize_wav(path: Path | str, *, language: str = "auto") -> str:
    """Transcribe the original ORION-captured WAV without ORION-side resampling.

    PR #104 validated this exact boundary on the target Windows PC: the native
    WASAPI WAV is passed directly to whisper-cli.exe, whisper.cpp performs its
    own decoding/resampling, and the process working directory is the pinned
    whisper runtime directory so native DLL discovery is deterministic.
    """
    if not runtime_ready():
        raise RuntimeError("Whisper medium is not prepared. Install speech recognition from Launcher first.")

    cli = whisper_cli_path()
    model = whisper_model_path()
    source = Path(path).resolve()
    if not source.is_file():
        raise RuntimeError(f"Whisper input WAV does not exist: {source}")

    with tempfile.TemporaryDirectory(prefix="orion-whisper-result-") as temp:
        output_base = Path(temp) / "transcript"
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

        completed = _run_direct(command, cwd=cli.parent)
        if completed.returncode != 0 and _is_windows_portable_recovery_status(completed.returncode):
            root = cli.parent
            status = _windows_status(completed.returncode)
            if _portable_backend_available(root):
                _force_portable_cpu_backend(root, trigger_status=status)
                completed = _run_direct(command, cwd=cli.parent)
                if completed.returncode != 0:
                    raise RuntimeError(f"Whisper STT failed: {_failure_detail(completed, recovered=True)}")
            else:
                raise RuntimeError(
                    f"Whisper STT failed with recoverable Windows backend status 0x{status:08X}, "
                    "and the pinned ggml-cpu.dll backend is unavailable"
                )
        elif completed.returncode != 0:
            raise RuntimeError(f"Whisper STT failed: {_failure_detail(completed)}")

        transcript_path = output_base.with_suffix(".txt")
        if transcript_path.is_file():
            text = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
        else:
            text = completed.stdout.strip()
        return " ".join(text.split())
