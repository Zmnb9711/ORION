from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from orion.whisper_cpp_stt import configured_threads, runtime_ready, whisper_cli_path, whisper_model_path


def recognize_wav(path: Path, *, language: str = "auto") -> str:
    """Transcribe the original captured WAV exactly as validated on Windows.

    whisper.cpp already accepts the native WASAPI WAV produced by ORION and
    performs its own audio decoding/resampling. Keep the CLI working directory
    at the runtime directory as well, matching the validated manual launch and
    keeping native DLL discovery deterministic.
    """
    if not runtime_ready():
        raise RuntimeError("Whisper medium is not prepared. Install speech recognition from Launcher first.")

    cli = whisper_cli_path()
    model = whisper_model_path()
    source = Path(path).resolve()
    if not source.is_file():
        raise RuntimeError(f"Whisper input WAV does not exist: {source}")

    with tempfile.TemporaryDirectory(prefix="orion-whisper-result-") as tmp:
        output_base = Path(tmp) / "transcript"
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
        completed = subprocess.run(
            command,
            cwd=str(cli.parent),
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no process output"
            status = completed.returncode & 0xFFFFFFFF
            raise RuntimeError(
                f"Whisper STT failed: exit={completed.returncode} status=0x{status:08X}; {detail}"
            )

        transcript_path = output_base.with_suffix(".txt")
        if transcript_path.is_file():
            text = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
        else:
            text = completed.stdout.strip()
        return " ".join(text.split())
