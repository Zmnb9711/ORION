from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.mission_bridge_ingest import MissionBridgeState, mission_bridge_telemetry


class ReadinessLevel(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


class ReadinessCheck(BaseModel):
    check_id: str
    label: str
    ok: bool
    message: str


class MissionReadiness(BaseModel):
    level: ReadinessLevel
    mission_data_current: bool
    checks: list[ReadinessCheck] = Field(default_factory=list)
    message: str


def assess_mission_readiness(state: MissionBridgeState | None = None) -> MissionReadiness:
    current = state or mission_bridge_telemetry.state()
    checks = [
        ReadinessCheck(
            check_id="bridge_connected",
            label="Mission Bridge connection",
            ok=current.connected,
            message="Connected" if current.connected else "Mission Bridge is not connected",
        ),
        ReadinessCheck(
            check_id="telemetry_current",
            label="Mission telemetry",
            ok=current.last_received_at is not None and not current.stale,
            message=(
                "Telemetry is current"
                if current.last_received_at is not None and not current.stale
                else "Telemetry is missing or stale"
            ),
        ),
        ReadinessCheck(
            check_id="mission_session",
            label="Mission session",
            ok=bool(current.session_id),
            message="Mission session identified" if current.session_id else "No active mission session",
        ),
        ReadinessCheck(
            check_id="coalition_units",
            label="Coalition unit catalogue",
            ok=current.unit_count > 0,
            message=(
                f"{current.unit_count} coalition units available"
                if current.unit_count > 0
                else "No coalition units received"
            ),
        ),
    ]
    mission_data_current = current.connected and not current.stale and current.last_received_at is not None
    failed = sum(not item.ok for item in checks)
    if mission_data_current and failed == 0:
        level = ReadinessLevel.READY
        message = "Mission data is current and ORION is ready for mission-aware requests"
    elif mission_data_current:
        level = ReadinessLevel.DEGRADED
        message = "Mission Bridge is live, but some mission-aware functions have limited data"
    else:
        level = ReadinessLevel.NOT_READY
        message = "Mission-aware answers are unavailable until current Mission Bridge data is received"
    return MissionReadiness(
        level=level,
        mission_data_current=mission_data_current,
        checks=checks,
        message=message,
    )


def require_current_mission_data() -> MissionBridgeState:
    state = mission_bridge_telemetry.state()
    if not state.connected or state.stale or state.last_received_at is None:
        raise RuntimeError("Mission Bridge telemetry is unavailable or stale")
    return state
