from fastapi import APIRouter

from orion.mission_context import LiveMissionContext, build_live_mission_context


router = APIRouter(prefix="/v1/mission-context", tags=["Mission context"])


@router.get("", response_model=LiveMissionContext)
def get_mission_context() -> LiveMissionContext:
    return build_live_mission_context()
