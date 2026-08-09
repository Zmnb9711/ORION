from fastapi import APIRouter

from orion.mission_control_coordination_runtime import (
    MissionControlCoordinationRuntimeStatus,
    coordination_mission_control,
)
from orion.mission_control_proactive import ProactiveMissionControlStatus, proactive_mission_control


router = APIRouter(prefix="/v1/mission-control", tags=["Mission Control"])


@router.get("/proactive/status", response_model=ProactiveMissionControlStatus)
def get_proactive_mission_control_status() -> ProactiveMissionControlStatus:
    return proactive_mission_control.status()


@router.get("/coordination/status", response_model=MissionControlCoordinationRuntimeStatus)
def get_coordination_mission_control_status() -> MissionControlCoordinationRuntimeStatus:
    return coordination_mission_control.status()
