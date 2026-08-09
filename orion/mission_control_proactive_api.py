from fastapi import APIRouter

from orion.mission_control_proactive import ProactiveMissionControlStatus, proactive_mission_control


router = APIRouter(prefix="/v1/mission-control/proactive", tags=["Mission Control"])


@router.get("/status", response_model=ProactiveMissionControlStatus)
def get_proactive_mission_control_status() -> ProactiveMissionControlStatus:
    return proactive_mission_control.status()
