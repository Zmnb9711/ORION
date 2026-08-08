from fastapi import APIRouter

from orion.mission_control_queries import MissionControlQuery, MissionControlQueryResult, execute_mission_control_query


router = APIRouter(prefix="/v1/mission-control", tags=["Mission Control"])


@router.post("/query", response_model=MissionControlQueryResult)
def query_mission_control(payload: MissionControlQuery) -> MissionControlQueryResult:
    return execute_mission_control_query(payload)
