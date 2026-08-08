from __future__ import annotations

from fastapi import APIRouter

from orion.mission_control_autonomy import MissionControlAutonomyDecision, evaluate_mission_control_autonomy


router = APIRouter(prefix="/v1/mission-control/autonomy", tags=["Mission Control"])


@router.get("/decision", response_model=MissionControlAutonomyDecision)
def get_autonomy_decision() -> MissionControlAutonomyDecision:
    return evaluate_mission_control_autonomy()
