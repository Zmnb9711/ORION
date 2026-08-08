from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from orion.dcs_process import DcsProcessRecord, dcs_processes
from orion.launch_profiles import DcsLaunchProfile, build_launch_plan, launch_profiles
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
    return None


def start_dcs_for_recovery() -> RecoveryLaunchStatus:
    profile = _resolve_recovery_profile()
    profiles = launch_profiles.list()
    if profile is None:
        if not profiles:
            return RecoveryLaunchStatus(
                state=RecoveryLaunchState.SELECTION_REQUIRED,
                message="No launch profile exists; create or select a DCS launch profile first",
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
