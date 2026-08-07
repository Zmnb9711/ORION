from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orion.mission_activation import (
    MissionActivationPlan,
    apply_guarded_activation,
    plan_activation,
)

router = APIRouter(prefix="/v1/mission-manager", tags=["mission-manager"])


class MissionActivationRequest(BaseModel):
    mission_path: str


@router.post("/activation-plan", response_model=MissionActivationPlan)
def create_activation_plan(payload: MissionActivationRequest) -> MissionActivationPlan:
    try:
        return plan_activation(payload.mission_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/activate", response_model=MissionActivationPlan)
def activate_mission_pack(payload: MissionActivationRequest) -> MissionActivationPlan:
    try:
        return apply_guarded_activation(payload.mission_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
