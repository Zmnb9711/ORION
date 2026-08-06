from fastapi import APIRouter, HTTPException

from orion.mission_bridge_ingest import (
    MissionBridgeDelta,
    MissionBridgeHeartbeat,
    MissionBridgeIngestResult,
    MissionBridgeSnapshot,
    MissionBridgeState,
    mission_bridge_telemetry,
)
from orion.mission_readiness import MissionReadiness, assess_mission_readiness

router = APIRouter(prefix="/v1/mission-bridge", tags=["Mission Bridge"])


@router.post("/snapshot", response_model=MissionBridgeIngestResult)
def ingest_mission_bridge_snapshot(payload: MissionBridgeSnapshot) -> MissionBridgeIngestResult:
    return mission_bridge_telemetry.ingest(payload)


@router.post("/delta", response_model=MissionBridgeIngestResult)
def ingest_mission_bridge_delta(payload: MissionBridgeDelta) -> MissionBridgeIngestResult:
    return mission_bridge_telemetry.apply_delta(payload)


@router.post("/heartbeat", response_model=MissionBridgeIngestResult)
def ingest_mission_bridge_heartbeat(payload: MissionBridgeHeartbeat) -> MissionBridgeIngestResult:
    return mission_bridge_telemetry.heartbeat(payload)


@router.get("/state", response_model=MissionBridgeState)
def get_mission_bridge_state() -> MissionBridgeState:
    return mission_bridge_telemetry.state()


@router.get("/readiness", response_model=MissionReadiness)
def get_mission_bridge_readiness() -> MissionReadiness:
    return assess_mission_readiness()


@router.put("/stale-timeout", response_model=MissionBridgeState)
def set_mission_bridge_stale_timeout(seconds: float) -> MissionBridgeState:
    try:
        return mission_bridge_telemetry.configure_stale_timeout(seconds)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/disconnect", response_model=MissionBridgeState)
def disconnect_mission_bridge(session_id: str | None = None, clear_indexes: bool = True) -> MissionBridgeState:
    return mission_bridge_telemetry.disconnect(session_id=session_id, clear_indexes=clear_indexes)
