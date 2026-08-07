from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Callable, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.launch_profiles import DcsLaunchPlan


class ProcessState(StrEnum):
    STARTED = "started"
    EXITED = "exited"


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...


class DcsProcessRecord(BaseModel):
    launch_id: UUID = Field(default_factory=uuid4)
    profile_id: UUID
    pid: int
    executable: str
    arguments: list[str]
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state: ProcessState = ProcessState.STARTED
    exit_code: int | None = None


Launcher = Callable[[DcsLaunchPlan], ProcessHandle]


def _default_launcher(plan: DcsLaunchPlan) -> ProcessHandle:
    # shell=False is intentional: arguments are passed as a list and never interpreted by cmd.exe.
    return subprocess.Popen(
        [plan.executable, *plan.arguments],
        cwd=plan.working_directory,
        shell=False,
        close_fds=True,
    )


class DcsProcessManager:
    def __init__(self, launcher: Launcher = _default_launcher) -> None:
        self._launcher = launcher
        self._records: dict[UUID, DcsProcessRecord] = {}
        self._handles: dict[UUID, ProcessHandle] = {}
        self._lock = RLock()

    def launch(self, profile_id: UUID, plan: DcsLaunchPlan) -> DcsProcessRecord:
        with self._lock:
            running = self._running_for_profile(profile_id)
            if running is not None:
                raise RuntimeError(f"DCS is already running for this profile (PID {running.pid})")

            handle = self._launcher(plan)
            record = DcsProcessRecord(
                profile_id=profile_id,
                pid=handle.pid,
                executable=plan.executable,
                arguments=list(plan.arguments),
            )
            self._records[record.launch_id] = record
            self._handles[record.launch_id] = handle
            return record

    def list(self) -> list[DcsProcessRecord]:
        with self._lock:
            self._refresh_all()
            return list(self._records.values())

    def get(self, launch_id: UUID) -> DcsProcessRecord | None:
        with self._lock:
            self._refresh(launch_id)
            return self._records.get(launch_id)

    def _running_for_profile(self, profile_id: UUID) -> DcsProcessRecord | None:
        self._refresh_all()
        return next(
            (
                item
                for item in self._records.values()
                if item.profile_id == profile_id and item.state is ProcessState.STARTED
            ),
            None,
        )

    def _refresh_all(self) -> None:
        for launch_id in list(self._handles):
            self._refresh(launch_id)

    def _refresh(self, launch_id: UUID) -> None:
        handle = self._handles.get(launch_id)
        record = self._records.get(launch_id)
        if handle is None or record is None or record.state is ProcessState.EXITED:
            return
        exit_code = handle.poll()
        if exit_code is not None:
            self._records[launch_id] = record.model_copy(
                update={"state": ProcessState.EXITED, "exit_code": exit_code}
            )
            self._handles.pop(launch_id, None)


dcs_processes = DcsProcessManager()
