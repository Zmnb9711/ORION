from fastapi import APIRouter

from orion.mission_control_coordination_runtime import (
    MissionControlCoordinationRuntimeStatus,
    coordination_mission_control,
)


router = APIRouter(prefix="/v1/mission-control/coordination", tags=["Mission Control"])


@router.get("/status", response_model=MissionControlCoordinationRuntimeStatus)
def get_coordination_mission_control_status() -> MissionControlCoordinationRuntimeStatus:
    return coordination_mission_control.status()
