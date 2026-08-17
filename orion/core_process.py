from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


class CoreProcessManager:
    """Manage ORION Core as a process separate from the desktop launcher.

    ``start`` ensures a Core process exists. ``stop`` intentionally only
    detaches the launcher without stopping Core. ``shutdown`` is the explicit
    lifecycle operation used only by full ORION Exit.
    """

    GRACEFUL_STOP_TIMEOUT = 3.0
    FORCE_STOP_TIMEOUT = 2.0

    def __init__(self, host: str, port: int, runtime_dir: Path) -> None:
        self.host = host
        self.port = port
        self.runtime_dir = runtime_dir
        self._process: subprocess.Popen[bytes] | None = None
        self._owns_process = False
        self._managed_pid: int | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def owns_process(self) -> bool:
        return self._owns_process

    @property
    def _pid_path(self) -> Path:
        return self.runtime_dir / "orion-core.pid"

    def healthy(self, timeout: float = 0.5) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8")).get("status") == "ok"
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False

    def _read_runtime_pid(self) -> int | None:
        try:
            value = int(self._pid_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _windows_image_name(pid: int) -> str | None:
        try:
            result = subprocess.run(  # noqa: S603, S607
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3.0,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        rows = list(csv.reader(io.StringIO(result.stdout)))
        if not rows or len(rows[0]) < 2:
            return None
        if rows[0][0].startswith("INFO:"):
            return None
        try:
            listed_pid = int(rows[0][1])
        except ValueError:
            return None
        return rows[0][0] if listed_pid == pid else None

    def _validated_runtime_pid(self) -> int | None:
        pid = self._read_runtime_pid()
        if pid is None:
            return None
        if os.name != "nt":
            return pid
        image = self._windows_image_name(pid)
        if image is None or image.casefold() != "orion-core.exe":
            return None
        return pid

    @staticmethod
    def _taskkill_pid(pid: int, *, force: bool) -> None:
        command = ["taskkill", "/PID", str(pid)]
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

    def _wait_until_core_stops(self, pid: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.name == "nt":
                if self._windows_image_name(pid) is None:
                    return True
            elif not self.healthy(timeout=0.2):
                return True
            time.sleep(0.1)
        return False

    def start(self) -> None:
        # Reuse an already-running ORION Core instead of spawning a duplicate.
        # If it belongs to this runtime/build, retain its validated PID so full
        # tray Exit can still enforce Core=0.
        if self.healthy():
            self._process = None
            self._owns_process = False
            self._managed_pid = self._validated_runtime_pid()
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
        self._managed_pid = self._process.pid

    def stop(self) -> None:
        """Detach the launcher without shutting down ORION Core."""
        self._process = None
        self._owns_process = False
        self._managed_pid = None

    def shutdown(self) -> None:
        """Stop the ORION Core associated with this Launcher/runtime.

        A Core spawned by this manager is stopped through its Popen handle. A
        reused Core is stopped only when its runtime PID can be validated as the
        packaged ``ORION-Core.exe``. Global image-name killing is forbidden.
        """
        process = self._process
        if process is not None and self._owns_process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.GRACEFUL_STOP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.FORCE_STOP_TIMEOUT)
            self._process = None
            self._owns_process = False
            self._managed_pid = None
            return

        pid = self._managed_pid or self._validated_runtime_pid()
        if pid is None:
            self._process = None
            self._owns_process = False
            self._managed_pid = None
            return

        if os.name == "nt":
            try:
                self._taskkill_pid(pid, force=False)
                if not self._wait_until_core_stops(pid, self.GRACEFUL_STOP_TIMEOUT):
                    self._taskkill_pid(pid, force=True)
                    self._wait_until_core_stops(pid, self.FORCE_STOP_TIMEOUT)
            except OSError:
                pass

        self._process = None
        self._owns_process = False
        self._managed_pid = None

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
