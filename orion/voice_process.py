from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class VoiceProcessManager:
    """Own the local microphone/STT worker independently from ORION Core."""

    def __init__(self, runtime_dir: Path, core_base_url: str) -> None:
        self.runtime_dir = runtime_dir
        self.core_base_url = core_base_url.rstrip("/")
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.running:
            return
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["ORION_RUNTIME_DIR"] = str(self.runtime_dir)
        env["ORION_CORE_BASE_URL"] = self.core_base_url
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        self._process = subprocess.Popen(  # noqa: S603
            self._command(),
            cwd=str(self.runtime_dir.parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        self._process = None

    def _command(self) -> list[str]:
        override = os.environ.get("ORION_VOICE_EXECUTABLE")
        if override:
            return [override]
        if getattr(sys, "frozen", False):
            launcher_dir = Path(sys.executable).resolve().parent
            candidates = (
                launcher_dir.parent / "Voice" / "ORION-Voice.exe",
                launcher_dir / "ORION-Voice.exe",
            )
            for candidate in candidates:
                if candidate.is_file():
                    return [str(candidate)]
            raise FileNotFoundError("ORION Voice is not installed. Expected ORION-Voice.exe in the ORION Voice directory.")
        return [sys.executable, "-m", "orion.whisper_voice_worker"]
