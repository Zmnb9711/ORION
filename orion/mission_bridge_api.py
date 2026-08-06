from fastapi import APIRouter

from orion.mission_bridge_ingest import (
    MissionBridgeIngestResult,
    MissionBridgeSnapshot,
    MissionBridgeState,
    mission_bridge_telemetry,
)

router = APIRouter(prefix="/v1/mission-bridge", tags=["Mission Bridge"])


@router.post("/snapshot", response_model=MissionBridgeIngestResult)
def ingest_mission_bridge_snapshot(payload: MissionBridgeSnapshot) -> MissionBridgeIngestResult:
    return mission_bridge_telemetry.ingest(payload)


@router.get("/state", response_model=MissionBridgeState)
def get_mission_bridge_state() -> MissionBridgeState:
    return mission_bridge_telemetry.state()


@router.post("/disconnect", response_model=MissionBridgeState)
def disconnect_mission_bridge(session_id: str | None = None, clear_indexes: bool = True) -> MissionBridgeState:
    return mission_bridge_telemetry.disconnect(session_id=session_id, clear_indexes=clear_indexes)
