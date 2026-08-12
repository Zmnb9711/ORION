from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from orion.dcs_process import DcsProcessRecord, dcs_processes
from orion.launch_profiles import (
    DcsLaunchProfile,
    DcsLaunchProfileCreate,
    build_launch_plan,
    launch_profiles,
)
from orion.orion_settings import orion_settings
from orion.telemetry_handshake import telemetry_handshake


class RecoveryLaunchState(StrEnum):
    STARTING = "starting"
    WAITING_FOR_TELEMETRY = "waiting_for_telemetry"
    CONNECTED = "connected"
    SELECTION_REQUIRED = "selection_required"
    FAILED = "failed"


class RecoveryLaunchStatus(BaseModel):
    state: RecoveryLaunchState
    message: str
    profile_id: UUID | None = None
    launch_id: UUID | None = None
    pid: int | None = None
    telemetry_connected: bool = False
    aircraft_type: str | None = None


def _resolve_recovery_profile() -> DcsLaunchProfile | None:
    settings = orion_settings.get()
    if settings.default_profile_id:
        try:
            profile_id = UUID(settings.default_profile_id)
        except ValueError:
            profile_id = None
        if profile_id is not None:
            selected = launch_profiles.get(profile_id)
            if selected is not None:
                return selected

    profiles = launch_profiles.list()
    if len(profiles) == 1:
        return profiles[0]
    if profiles:
        return None

    # First-run setup persists the active DCS installation independently from
    # launch profiles. A user must be able to press LAUNCH DCS immediately
    # after setup without creating a separate profile first. Create a transient
    # default profile in the Core process; LaunchProfileStore validates that a
    # persisted active installation is actually available.
    try:
        return launch_profiles.create(
            DcsLaunchProfileCreate(name="Active DCS", use_active_installation=True)
        )
    except KeyError:
        return None


def start_dcs_for_recovery() -> RecoveryLaunchStatus:
    # Launch profiles, DCS process records and telemetry handshake are Core-owned
    # in-memory state. A Launcher-side button must delegate the operation to the
    # Core API rather than create a parallel Launcher-local state universe.
    if os.environ.get("ORION_PROCESS_ROLE") == "launcher":
        return _start_dcs_via_core()
    return _start_dcs_local()


def _start_dcs_local() -> RecoveryLaunchStatus:
    profile = _resolve_recovery_profile()
    profiles = launch_profiles.list()
    if profile is None:
        if not profiles:
            return RecoveryLaunchStatus(
                state=RecoveryLaunchState.SELECTION_REQUIRED,
                message="No active DCS installation is configured; complete DCS Setup first",
            )
        return RecoveryLaunchStatus(
            state=RecoveryLaunchState.SELECTION_REQUIRED,
            message="Multiple launch profiles exist; select a default launch profile first",
        )

    try:
        plan = build_launch_plan(profile)
        record: DcsProcessRecord = dcs_processes.launch(profile.profile_id, plan)
    except (KeyError, ValueError, OSError, RuntimeError) as exc:
        return RecoveryLaunchStatus(
            state=RecoveryLaunchState.FAILED,
            message=str(exc),
            profile_id=profile.profile_id,
        )

    live = telemetry_handshake.snapshot()
    return RecoveryLaunchStatus(
        state=(RecoveryLaunchState.CONNECTED if live.connected else RecoveryLaunchState.WAITING_FOR_TELEMETRY),
        message=("DCS launched and telemetry is connected" if live.connected else "DCS launched; waiting for live telemetry"),
        profile_id=profile.profile_id,
        launch_id=record.launch_id,
        pid=record.pid,
        telemetry_connected=live.connected,
        aircraft_type=live.aircraft_type,
    )


def recovery_launch_status(launch_id: UUID | None = None) -> RecoveryLaunchStatus:
    if os.environ.get("ORION_PROCESS_ROLE") == "launcher":
        return _recovery_launch_status_via_core(launch_id)
    return _recovery_launch_status_local(launch_id)


def _recovery_launch_status_local(launch_id: UUID | None = None) -> RecoveryLaunchStatus:
    live = telemetry_handshake.snapshot()
    if live.connected:
        return RecoveryLaunchStatus(
            state=RecoveryLaunchState.CONNECTED,
            message="Live DCS telemetry is connected",
            launch_id=launch_id,
            telemetry_connected=True,
            aircraft_type=live.aircraft_type,
        )

    if launch_id is None:
        return RecoveryLaunchStatus(
            state=RecoveryLaunchState.WAITING_FOR_TELEMETRY,
            message="Waiting for live DCS telemetry",
        )

    record = dcs_processes.get(launch_id)
    if record is None:
        return RecoveryLaunchStatus(
            state=RecoveryLaunchState.FAILED,
            message="DCS launch record not found",
            launch_id=launch_id,
        )
    if record.state.value == "exited":
        return RecoveryLaunchStatus(
            state=RecoveryLaunchState.FAILED,
            message=f"DCS exited before telemetry connected (exit code {record.exit_code})",
            profile_id=record.profile_id,
            launch_id=record.launch_id,
            pid=record.pid,
        )
    return RecoveryLaunchStatus(
        state=RecoveryLaunchState.WAITING_FOR_TELEMETRY,
        message="DCS is running; waiting for live telemetry",
        profile_id=record.profile_id,
        launch_id=record.launch_id,
        pid=record.pid,
    )


def _core_base_url() -> str:
    return os.environ.get("ORION_CORE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _start_dcs_via_core() -> RecoveryLaunchStatus:
    request = urllib.request.Request(
        f"{_core_base_url()}/v1/recovery-launch/start",
        data=b"",
        method="POST",
    )
    return _request_core_status(request)


def _recovery_launch_status_via_core(launch_id: UUID | None) -> RecoveryLaunchStatus:
    query = ""
    if launch_id is not None:
        query = "?" + urllib.parse.urlencode({"launch_id": str(launch_id)})
    request = urllib.request.Request(f"{_core_base_url()}/v1/recovery-launch/status{query}", method="GET")
    return _request_core_status(request)


def _request_core_status(request: urllib.request.Request) -> RecoveryLaunchStatus:
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return RecoveryLaunchStatus(
            state=RecoveryLaunchState.FAILED,
            message=f"Unable to query ORION Core launch service: {exc}",
        )
    return RecoveryLaunchStatus.model_validate(payload)
