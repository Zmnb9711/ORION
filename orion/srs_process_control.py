"""Launcher-side discovery and start control for external SRS applications.

The official SRS Server and Client remain independently-owned applications.
This module can discover, inspect, and start them, but deliberately exposes no
stop, terminate, configuration mutation, or GUI-automation surface.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SrsProcessKind(StrEnum):
    SERVER = "server"
    CLIENT = "client"


class SrsProcessState(StrEnum):
    NOT_FOUND = "NOT FOUND"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class SrsProcessRecord:
    pid: int
    executable_path: str


@dataclass(frozen=True, slots=True)
class SrsProcessStatus:
    kind: SrsProcessKind
    state: SrsProcessState
    executable_path: str | None = None
    pid: int | None = None
    message: str = ""


ProcessInspector = Callable[[str], Sequence[SrsProcessRecord]]
ExecutableLauncher = Callable[[Path], None]
StatusCallback = Callable[[SrsProcessStatus], None]

_EXECUTABLE_NAMES = {
    SrsProcessKind.SERVER: "SRS-Server.exe",
    SrsProcessKind.CLIENT: "SR-ClientRadio.exe",
}


def _normal_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _known_roots(environment: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    env = os.environ if environment is None else environment
    roots: list[Path] = []
    for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        raw = str(env.get(name, "") or "").strip()
        if raw:
            root = Path(raw)
            if root not in roots:
                roots.append(root)
    return tuple(roots)


def srs_discovery_candidates(
    kind: SrsProcessKind,
    environment: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    """Return bounded standard candidates without recursively scanning disks."""

    executable = _EXECUTABLE_NAMES[kind]
    subdirectory = "Server" if kind is SrsProcessKind.SERVER else "Client"
    candidates: list[Path] = []
    for root in _known_roots(environment):
        install = root / "DCS-SimpleRadio-Standalone"
        candidates.extend((install / subdirectory / executable, install / executable))
    return tuple(dict.fromkeys(candidates))


def discover_srs_executable(
    kind: SrsProcessKind,
    configured_path: str = "",
    *,
    environment: Mapping[str, str] | None = None,
) -> Path | None:
    configured = configured_path.strip()
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_file() and candidate.name.casefold() == _EXECUTABLE_NAMES[kind].casefold() else None
    return next(
        (candidate for candidate in srs_discovery_candidates(kind, environment) if candidate.is_file()),
        None,
    )


def inspect_windows_processes(image_name: str) -> tuple[SrsProcessRecord, ...]:
    """Inspect exact executable paths through the bounded Windows CIM surface."""

    allowed = {name.casefold() for name in _EXECUTABLE_NAMES.values()}
    if image_name.casefold() not in allowed:
        raise ValueError("Unsupported SRS process image")
    if os.name != "nt":
        return ()
    command = (
        f"Get-CimInstance Win32_Process -Filter \"Name='{image_name}'\" | "
        "Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(  # noqa: S603
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if result.returncode or not result.stdout.strip():
        return ()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ()
    items = payload if isinstance(payload, list) else [payload]
    records: list[SrsProcessRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = item.get("ExecutablePath")
        pid = item.get("ProcessId")
        if isinstance(path, str) and path and isinstance(pid, int) and pid > 0:
            records.append(SrsProcessRecord(pid, path))
    return tuple(records)


def launch_external_srs(executable: Path) -> None:
    if os.name != "nt" or not hasattr(os, "startfile"):
        raise OSError("External SRS launch is supported only on Windows")
    os.startfile(  # type: ignore[attr-defined]  # noqa: S606
        str(executable),
        cwd=str(executable.parent),
    )


def sanitize_process_error(error: BaseException, *secrets: str) -> str:
    value = f"{type(error).__name__}: {error}".replace("\r", " ").replace("\n", " ")
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[redacted]")
    return value[:300]


class SrsExternalProcessController:
    """Start-only controller; external SRS lifetime never belongs to ORION."""

    def __init__(
        self,
        *,
        inspector: ProcessInspector = inspect_windows_processes,
        launcher: ExecutableLauncher = launch_external_srs,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        startup_timeout: float = 3.0,
    ) -> None:
        self._inspector = inspector
        self._launcher = launcher
        self._clock = clock
        self._sleep = sleep
        self._startup_timeout = startup_timeout
        self._start_locks = {kind: threading.Lock() for kind in SrsProcessKind}

    def status(self, kind: SrsProcessKind, configured_path: str = "") -> SrsProcessStatus:
        executable = discover_srs_executable(kind, configured_path)
        if executable is None:
            detail = "Configured executable was not found" if configured_path.strip() else "SRS executable was not found"
            return SrsProcessStatus(kind, SrsProcessState.NOT_FOUND, message=detail)
        record = self._find_running(kind, executable)
        if record is None:
            return SrsProcessStatus(
                kind,
                SrsProcessState.STOPPED,
                executable_path=str(executable),
                message="Process is not running",
            )
        return SrsProcessStatus(
            kind,
            SrsProcessState.RUNNING,
            executable_path=str(executable),
            pid=record.pid,
            message="Process is running",
        )

    def start_server(
        self,
        configured_path: str = "",
        *,
        on_status: StatusCallback | None = None,
    ) -> SrsProcessStatus:
        return self._start(SrsProcessKind.SERVER, configured_path, on_status=on_status)

    def start_client(
        self,
        configured_path: str = "",
        *,
        server_path: str = "",
        on_status: StatusCallback | None = None,
    ) -> SrsProcessStatus:
        server = self.status(SrsProcessKind.SERVER, server_path)
        if server.state is not SrsProcessState.RUNNING:
            result = SrsProcessStatus(
                SrsProcessKind.CLIENT,
                SrsProcessState.ERROR,
                message="Start SRS Server first.",
            )
            if on_status is not None:
                on_status(result)
            return result
        return self._start(SrsProcessKind.CLIENT, configured_path, on_status=on_status)

    def _start(
        self,
        kind: SrsProcessKind,
        configured_path: str,
        *,
        on_status: StatusCallback | None,
    ) -> SrsProcessStatus:
        with self._start_locks[kind]:
            return self._start_locked(kind, configured_path, on_status=on_status)

    def _start_locked(
        self,
        kind: SrsProcessKind,
        configured_path: str,
        *,
        on_status: StatusCallback | None,
    ) -> SrsProcessStatus:
        current = self.status(kind, configured_path)
        if current.state in {SrsProcessState.NOT_FOUND, SrsProcessState.RUNNING}:
            if on_status is not None:
                on_status(current)
            return current
        executable = Path(str(current.executable_path))
        starting = SrsProcessStatus(
            kind,
            SrsProcessState.STARTING,
            executable_path=str(executable),
            message="Starting external SRS process",
        )
        if on_status is not None:
            on_status(starting)
        try:
            self._launcher(executable)
        except Exception as exc:
            result = SrsProcessStatus(
                kind,
                SrsProcessState.ERROR,
                executable_path=str(executable),
                message=sanitize_process_error(exc),
            )
            if on_status is not None:
                on_status(result)
            return result

        deadline = self._clock() + self._startup_timeout
        while self._clock() < deadline:
            record = self._find_running(kind, executable)
            if record is not None:
                result = SrsProcessStatus(
                    kind,
                    SrsProcessState.RUNNING,
                    executable_path=str(executable),
                    pid=record.pid,
                    message="Process is running",
                )
                if on_status is not None:
                    on_status(result)
                return result
            self._sleep(0.1)
        result = SrsProcessStatus(
            kind,
            SrsProcessState.ERROR,
            executable_path=str(executable),
            message="SRS process did not remain running after launch.",
        )
        if on_status is not None:
            on_status(result)
        return result

    def _find_running(self, kind: SrsProcessKind, executable: Path) -> SrsProcessRecord | None:
        target = _normal_path(executable)
        return next(
            (
                record
                for record in self._inspector(_EXECUTABLE_NAMES[kind])
                if _normal_path(record.executable_path) == target
            ),
            None,
        )


def launcher_srs_offline_smoke() -> dict[str, object]:
    """Frozen Launcher import smoke with no process, network, or audio activity."""

    candidates = sum(
        (len(srs_discovery_candidates(kind, {})) for kind in SrsProcessKind),
        0,
    )
    return {
        "ok": set(_EXECUTABLE_NAMES.values()) == {"SRS-Server.exe", "SR-ClientRadio.exe"},
        "candidate_count_without_environment": candidates,
        "external_process_started": False,
        "network_used": False,
        "audio_devices_opened": False,
    }
