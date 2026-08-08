from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from orion.mission_control_jtac import MissionControlJtacRequest, MissionControlJtacResult, orchestrate_jtac
from orion.mission_control_jtac_cancel import JtacCancellationResult, cancel_jtac


router = APIRouter(prefix="/v1/mission-control/jtac", tags=["Mission Control", "JTAC"])


@router.post("/orchestrate", response_model=MissionControlJtacResult, status_code=202)
def orchestrate(payload: MissionControlJtacRequest) -> MissionControlJtacResult:
    try:
        return orchestrate_jtac(payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/cancel", response_model=JtacCancellationResult, status_code=202)
def cancel(session_id: UUID) -> JtacCancellationResult:
    try:
        return cancel_jtac(session_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
