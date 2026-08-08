from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orion.confirmations import ConfirmationDecision, PendingAction
from orion.mission_control_autonomy import MissionControlAutonomyDecision, evaluate_mission_control_autonomy
from orion.mission_control_autonomy_actions import (
    MissionControlAutonomyResolution,
    create_autonomy_pending_action,
    resolve_autonomy_pending_action,
)


router = APIRouter(prefix="/v1/mission-control/autonomy", tags=["Mission Control"])


@router.get("/decision", response_model=MissionControlAutonomyDecision)
def get_autonomy_decision() -> MissionControlAutonomyDecision:
    return evaluate_mission_control_autonomy()


@router.post("/proposal", response_model=PendingAction, status_code=201)
def create_autonomy_proposal() -> PendingAction:
    try:
        return create_autonomy_pending_action(evaluate_mission_control_autonomy())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/proposal/{action_id}/decision", response_model=MissionControlAutonomyResolution)
def decide_autonomy_proposal(action_id: str, decision: ConfirmationDecision) -> MissionControlAutonomyResolution:
    try:
        return resolve_autonomy_pending_action(action_id, confirm=decision.confirm)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
