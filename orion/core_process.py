from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


class CoreProcessManager:
    """Manage ORION Core as a process separate from the desktop launcher.

    ``start`` ensures a Core process exists. ``stop`` intentionally only
    detaches the launcher from a Core that it started, preserving the product
    rule that closing the UI must not implicitly stop ORION. ``shutdown`` is
    the explicit lifecycle operation that terminates the owned Core process.
    """

    def __init__(self, host: str, port: int, runtime_dir: Path) -> None:
        self.host = host
        self.port = port
        self.runtime_dir = runtime_dir
        self._process: subprocess.Popen[bytes] | None = None
        self._owns_process = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def owns_process(self) -> bool:
        return self._owns_process

    def healthy(self, timeout: float = 0.5) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8")).get("status") == "ok"
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False

    def start(self) -> None:
        # Reuse an already-running Core instead of spawning a duplicate.
        if self.healthy():
            self._owns_process = False
            return
        if self._process is not None and self._process.poll() is None:
            return

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["ORION_RUNTIME_DIR"] = str(self.runtime_dir)
        command = self._command()
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        self._process = subprocess.Popen(  # noqa: S603
            command,
            cwd=str(self.runtime_dir.parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._owns_process = True

    def stop(self) -> None:
        """Detach the launcher without shutting down ORION Core."""
        self._process = None
        self._owns_process = False

    def shutdown(self) -> None:
        """Explicitly stop the Core process started by this launcher instance."""
        process = self._process
        if process is None or not self._owns_process:
            return
        if process.poll() is not None:
            self._process = None
            self._owns_process = False
            return
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
        finally:
            self._process = None
            self._owns_process = False

    def _command(self) -> list[str]:
        override = os.environ.get("ORION_CORE_EXECUTABLE")
        if override:
            return [override, "--host", self.host, "--port", str(self.port)]

        if getattr(sys, "frozen", False):
            launcher_dir = Path(sys.executable).resolve().parent
            candidates = (
                launcher_dir.parent / "Core" / "ORION-Core.exe",
                launcher_dir / "ORION-Core.exe",
            )
            for candidate in candidates:
                if candidate.is_file():
                    return [str(candidate), "--host", self.host, "--port", str(self.port)]
            raise FileNotFoundError("ORION Core is not installed. Expected ORION-Core.exe in the ORION Core directory.")

        return [sys.executable, "-m", "orion.core_main", "--host", self.host, "--port", str(self.port)]
