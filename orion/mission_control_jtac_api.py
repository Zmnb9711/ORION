from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orion.mission_control_jtac import MissionControlJtacRequest, MissionControlJtacResult, orchestrate_jtac


router = APIRouter(prefix="/v1/mission-control/jtac", tags=["Mission Control", "JTAC"])


@router.post("/orchestrate", response_model=MissionControlJtacResult, status_code=202)
def orchestrate(payload: MissionControlJtacRequest) -> MissionControlJtacResult:
    try:
        return orchestrate_jtac(payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
