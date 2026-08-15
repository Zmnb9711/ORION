from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from orion.whisper_cpp_stt import configured_threads, runtime_ready, whisper_cli_path, whisper_model_path


def _hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    """Hide the console window without CREATE_NO_WINDOW.

    The target Windows machine successfully runs whisper-cli.exe as a normal
    console process. CREATE_NO_WINDOW is deliberately avoided here so process
    creation semantics stay close to that validated manual launch while the
    launcher remains visually silent.
    """
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is None:
        return None
    startupinfo = startupinfo_type()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return startupinfo


def recognize_wav(path: Path, *, language: str = "auto") -> str:
    """Transcribe the original captured WAV exactly as validated on Windows.

    whisper.cpp already accepts the native WASAPI WAV produced by ORION and
    performs its own audio decoding/resampling. Keep the CLI working directory
    at the runtime directory and avoid pipe/CREATE_NO_WINDOW process semantics,
    matching the successful manual launch as closely as possible.
    """
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
            completed = subprocess.run(
                command,
                cwd=str(cli.parent),
                stdout=stdout_handle,
                stderr=stderr_handle,
                check=False,
                startupinfo=_hidden_startupinfo(),
            )

        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        if completed.returncode != 0:
            detail = stderr_text or stdout_text or "no process output"
            status = completed.returncode & 0xFFFFFFFF
            raise RuntimeError(
                f"Whisper STT failed: exit={completed.returncode} status=0x{status:08X}; {detail}"
            )

        transcript_path = output_base.with_suffix(".txt")
        if transcript_path.is_file():
            text = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
        else:
            text = stdout_text
        return " ".join(text.split())
