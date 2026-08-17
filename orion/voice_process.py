from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


class VoiceProcessManager:
    """Own the local microphone/STT worker independently from ORION Core."""

    GRACEFUL_STOP_TIMEOUT = 3.0
    FORCE_STOP_TIMEOUT = 2.0

    def __init__(self, runtime_dir: Path, core_base_url: str) -> None:
        self.runtime_dir = runtime_dir
        self.core_base_url = core_base_url.rstrip("/")
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def state_path(self) -> Path:
        return self.runtime_dir / "voice" / "state.json"

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def status(self) -> dict[str, object]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
        return {"state": "STARTING" if self.running else "STOPPED", "heard": "", "reply": ""}

    def _write_state(self, state: str, *, error: str = "") -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"state": state, "heard": "", "reply": "", "error": error, "updated_at": datetime.now(timezone.utc).isoformat()}
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

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
        self._write_state("STARTING")
        self._process = subprocess.Popen(self._command(), cwd=str(self.runtime_dir.parent), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)  # noqa: S603

    @staticmethod
    def _taskkill_tree(pid: int, *, force: bool) -> None:
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        subprocess.run(  # noqa: S603, S607
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def stop(self) -> None:
        """Stop the owned Voice process and its whisper-stream child tree.

        On Windows, containment is rooted at the exact Voice PID created by this
        manager. A normal tree termination is requested first. Only if that
        owned tree fails to exit within the bounded timeout is the same PID tree
        force-terminated. No image-name/global process kill is used.
        """
        process = self._process
        if process is None:
            self._write_state("STOPPED")
            return

        if process.poll() is None:
            if os.name == "nt":
                try:
                    self._taskkill_tree(process.pid, force=False)
                    process.wait(timeout=self.GRACEFUL_STOP_TIMEOUT)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        self._taskkill_tree(process.pid, force=True)
                        process.wait(timeout=self.FORCE_STOP_TIMEOUT)
                    except (OSError, subprocess.TimeoutExpired):
                        process.kill()
                        process.wait(timeout=self.FORCE_STOP_TIMEOUT)
            else:
                process.terminate()
                try:
                    process.wait(timeout=self.GRACEFUL_STOP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.FORCE_STOP_TIMEOUT)

        self._process = None
        self._write_state("STOPPED")

    def _command(self) -> list[str]:
        override = os.environ.get("ORION_VOICE_EXECUTABLE")
        if override:
            return [override]
        if getattr(sys, "frozen", False):
            launcher_dir = Path(sys.executable).resolve().parent
            for candidate in (launcher_dir.parent / "Voice" / "ORION-Voice.exe", launcher_dir / "ORION-Voice.exe"):
                if candidate.is_file():
                    return [str(candidate)]
            raise FileNotFoundError("ORION Voice is not installed. Expected ORION-Voice.exe in the ORION Voice directory.")
        return [sys.executable, "-m", "orion.whisper_voice_worker"]
