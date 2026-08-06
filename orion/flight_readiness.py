from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from orion.launch_profiles import DcsLaunchMode, DcsLaunchPlan, build_launch_plan, launch_profiles
from orion.mission_inspection import MissionPackState, inspect_mission


class ReadinessLevel(StrEnum):
    READY = "ready"
    LIMITED = "limited"
    BLOCKED = "blocked"


class ReadinessCheck(BaseModel):
    key: str
    label: str
    passed: bool
    blocking: bool
    message: str


class FlightReadinessRequest(BaseModel):
    profile_id: UUID
    mission_path: str | None = None
    ai_ready: bool = True
    flight_bridge_installed: bool = False
    voice_ready: bool = False


class FlightReadinessReport(BaseModel):
    level: ReadinessLevel
    ready_to_launch: bool
    profile_label: str
    map_name: str | None = None
    ai_status: str
    checks: list[ReadinessCheck] = Field(default_factory=list)
    launch_plan: DcsLaunchPlan | None = None


def evaluate_flight_readiness(payload: FlightReadinessRequest) -> FlightReadinessReport:
    profile = launch_profiles.get(payload.profile_id)
    if profile is None:
        raise KeyError("Launch profile not found")

    mission_value = payload.mission_path or profile.mission_path
    checks: list[ReadinessCheck] = []

    executable = Path(profile.dcs_executable)
    checks.append(
        ReadinessCheck(
            key="dcs_executable",
            label="DCS",
            passed=executable.is_file(),
            blocking=True,
            message="DCS executable found" if executable.is_file() else "DCS executable not found",
        )
    )

    mission_exists = bool(mission_value and Path(mission_value).is_file())
    checks.append(
        ReadinessCheck(
            key="mission",
            label="Mission",
            passed=mission_exists,
            blocking=True,
            message="Mission found" if mission_exists else "Mission file not found",
        )
    )

    mission_pack_ok = False
    mission_pack_message = "Mission Pack not checked"
    if mission_exists and mission_value:
        inspection = inspect_mission(mission_value)
        mission_pack_ok = inspection.state is MissionPackState.TRIGGER_DETECTED
        mission_pack_message = {
            MissionPackState.NOT_PREPARED: "Mission Pack not embedded",
            MissionPackState.EMBEDDED_ONLY: "Mission Pack embedded but not activated",
            MissionPackState.TRIGGER_DETECTED: "Mission Pack active",
        }[inspection.state]

    checks.append(
        ReadinessCheck(
            key="mission_pack",
            label="Mission Pack",
            passed=mission_pack_ok,
            blocking=False,
            message=mission_pack_message,
        )
    )

    checks.append(
        ReadinessCheck(
            key="flight_bridge",
            label="Flight Bridge",
            passed=payload.flight_bridge_installed,
            blocking=False,
            message="Flight Bridge ready" if payload.flight_bridge_installed else "Flight Bridge not confirmed",
        )
    )
    checks.append(
        ReadinessCheck(
            key="voice",
            label="Voice",
            passed=payload.voice_ready,
            blocking=False,
            message="Voice ready" if payload.voice_ready else "Voice input not ready",
        )
    )
    checks.append(
        ReadinessCheck(
            key="ai",
            label="AI",
            passed=payload.ai_ready,
            blocking=True,
            message="AI ready" if payload.ai_ready else "AI is not ready",
        )
    )

    blocking_failed = any(not check.passed and check.blocking for check in checks)
    optional_failed = any(not check.passed and not check.blocking for check in checks)
    if blocking_failed:
        level = ReadinessLevel.BLOCKED
    elif optional_failed:
        level = ReadinessLevel.LIMITED
    else:
        level = ReadinessLevel.READY

    mode_label = {
        DcsLaunchMode.DESKTOP: "Desktop",
        DcsLaunchMode.OPENXR: "OpenXR",
        DcsLaunchMode.STEAMVR: "SteamVR",
    }[profile.mode]

    return FlightReadinessReport(
        level=level,
        ready_to_launch=not blocking_failed,
        profile_label=f"{profile.name} ({mode_label})",
        ai_status="AI готов" if payload.ai_ready else "AI не готов",
        checks=checks,
        launch_plan=build_launch_plan(profile) if not blocking_failed else None,
    )
