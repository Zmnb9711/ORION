from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CoreShutdownResult:
    owned: bool
    pid: int | None
    graceful_requested: bool
    graceful_exit: bool
    fallback_terminate: bool
    fallback_kill: bool
    process_exited: bool
    udp_released: bool | None


class CoreProcessManager:
    """Manage the Core process created by this exact Launcher instance.

    A live child ``Popen`` handle plus an unlogged random lifecycle token is the
    ownership proof. A healthy Core found before startup is usable but external:
    it is never adopted or terminated from a PID file, image name, path or port.
    """

    GRACEFUL_STOP_TIMEOUT = 3.0
    TERMINATE_TIMEOUT = 2.0
    KILL_TIMEOUT = 2.0
    UDP_RELEASE_TIMEOUT = 2.0
    LIFECYCLE_LOG_LIMIT = 64 * 1024

    def __init__(self, host: str, port: int, runtime_dir: Path) -> None:
        self.host = host
        self.port = port
        self.runtime_dir = runtime_dir
        self._process: subprocess.Popen[bytes] | None = None
        self._owns_process = False
        self._shutdown_token: str | None = None
        self.last_shutdown: CoreShutdownResult | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def owns_process(self) -> bool:
        return self._owns_process

    @property
    def managed_pid(self) -> int | None:
        process = self._process
        return process.pid if process is not None and self._owns_process else None

    @property
    def _lifecycle_log_path(self) -> Path:
        return self.runtime_dir / "launcher-lifecycle.jsonl"

    def record_lifecycle(self, event: str, **fields: object) -> None:
        """Append one bounded, credential-free lifecycle diagnostic."""

        allowed = {
            key: value
            for key, value in fields.items()
            if key in {"pid", "owned", "reason", "graceful", "fallback", "udp_released"}
            and isinstance(value, (bool, int, str, type(None)))
        }
        payload = {"timestamp": datetime.now(UTC).isoformat(), "event": event, **allowed}
        try:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            path = self._lifecycle_log_path
            if path.is_file() and path.stat().st_size >= self.LIFECYCLE_LOG_LIMIT:
                data = path.read_bytes()[-(self.LIFECYCLE_LOG_LIMIT // 2) :]
                newline = data.find(b"\n")
                path.write_bytes(data[newline + 1 :] if newline >= 0 else b"")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        except OSError:
            return

    def healthy(self, timeout: float = 0.5) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8")).get("status") == "ok"
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False

    def start(self) -> None:
        self.record_lifecycle("launcher_started", owned=False)
        if self.healthy():
            self._process = None
            self._owns_process = False
            self._shutdown_token = None
            self.record_lifecycle("launcher_attached_external_core", owned=False)
            return
        if self._process is not None and self._process.poll() is None:
            return

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(32)
        env = os.environ.copy()
        env["ORION_RUNTIME_DIR"] = str(self.runtime_dir)
        env["ORION_LAUNCHER_SHUTDOWN_TOKEN"] = token
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(  # noqa: S603
            self._command(),
            cwd=str(self.runtime_dir.parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._process = process
        self._owns_process = True
        self._shutdown_token = token
        self.record_lifecycle("core_ownership_established", pid=process.pid, owned=True)

    def stop(self) -> None:
        """Detach without stopping Core; used only by non-canonical legacy runners."""

        self.record_lifecycle("launcher_detached_core", pid=self.managed_pid, owned=self._owns_process)
        self._process = None
        self._owns_process = False
        self._shutdown_token = None

    def _request_graceful_shutdown(self, token: str) -> bool:
        request = urllib.request.Request(
            f"{self.base_url}/v1/lifecycle/shutdown",
            data=b"",
            headers={"X-ORION-Lifecycle-Token": token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=1.0) as response:
                return response.status == 202
        except (OSError, urllib.error.URLError):
            return False

    @staticmethod
    def _wait_for_process(process: subprocess.Popen[bytes], timeout: float) -> bool:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        except OSError:
            return process.poll() is not None
        return True

    @staticmethod
    def _udp_port_available(host: str, port: int) -> bool:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as probe:
                probe.bind((host, port))
        except OSError:
            return False
        return True

    def _wait_for_udp_release(self) -> bool:
        host = os.environ.get("ORION_FLIGHT_BRIDGE_HOST", "127.0.0.1")
        try:
            port = int(os.environ.get("ORION_FLIGHT_BRIDGE_TELEMETRY_PORT", "45100"))
        except ValueError:
            return False
        deadline = time.monotonic() + self.UDP_RELEASE_TIMEOUT
        while time.monotonic() < deadline:
            if self._udp_port_available(host, port):
                return True
            time.sleep(0.05)
        return False

    def shutdown(self) -> CoreShutdownResult:
        """Gracefully stop only the exact Core child created by this manager."""

        process = self._process
        token = self._shutdown_token
        pid = process.pid if process is not None else None
        if process is None or not self._owns_process or token is None:
            result = CoreShutdownResult(False, pid, False, False, False, False, False, None)
            self.record_lifecycle("external_core_preserved", pid=pid, owned=False)
            self._clear_ownership(result)
            return result

        graceful_requested = False
        graceful_exit = process.poll() is not None
        fallback_terminate = False
        fallback_kill = False
        self.record_lifecycle("graceful_core_shutdown_requested", pid=pid, owned=True)

        if not graceful_exit:
            graceful_requested = self._request_graceful_shutdown(token)
            if graceful_requested:
                graceful_exit = self._wait_for_process(process, self.GRACEFUL_STOP_TIMEOUT)

        if not graceful_exit and process.poll() is None:
            fallback_terminate = True
            self.record_lifecycle("graceful_core_shutdown_timeout", pid=pid, owned=True)
            try:
                process.terminate()
            except OSError:
                pass
            if not self._wait_for_process(process, self.TERMINATE_TIMEOUT) and process.poll() is None:
                fallback_kill = True
                try:
                    process.kill()
                except OSError:
                    pass
                self._wait_for_process(process, self.KILL_TIMEOUT)

        process_exited = process.poll() is not None
        udp_released = self._wait_for_udp_release() if process_exited else False
        result = CoreShutdownResult(
            True,
            pid,
            graceful_requested,
            graceful_exit,
            fallback_terminate,
            fallback_kill,
            process_exited,
            udp_released,
        )
        self.record_lifecycle(
            "core_exit_complete" if process_exited else "core_exit_failed",
            pid=pid,
            owned=True,
            graceful=graceful_exit,
            fallback=fallback_terminate,
            udp_released=udp_released,
        )
        self._clear_ownership(result)
        return result

    def _clear_ownership(self, result: CoreShutdownResult) -> None:
        self.last_shutdown = result
        self._process = None
        self._owns_process = False
        self._shutdown_token = None

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
