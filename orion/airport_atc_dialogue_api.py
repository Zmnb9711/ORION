from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.airport_arrival_orchestration import AirportArrivalOrchestrator
from orion.airport_arrival_runtime import AirportArrivalRuntime
from orion.airport_atc_dialogue import AtcDialogueRequest, AtcDialogueResult, AirportAtcDialogueGateway
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.atc_service import virtual_atc


router = APIRouter(prefix="/v1/atc", tags=["Virtual ATC"])

_surface = AirportSurfaceCoordinator(virtual_atc.core)
_arrival = AirportArrivalRuntime(_surface)
_arrival_orchestration = AirportArrivalOrchestrator(service=virtual_atc, arrival=_arrival)
atc_dialogue = AirportAtcDialogueGateway(
    service=virtual_atc,
    arrival=_arrival,
    arrival_orchestrator=_arrival_orchestration,
)


class ArrivalStartRequest(BaseModel):
    runway_id: str = Field(min_length=1, max_length=40)
    reason: str = Field(default="arrival contact established", min_length=1, max_length=500)


@router.post("/sessions/{session_id}/arrival/start", response_model=AtcDialogueResult, status_code=201)
def start_arrival_session(session_id: UUID, payload: ArrivalStartRequest) -> AtcDialogueResult:
    try:
        virtual_atc.status(session_id)
        session = _arrival_orchestration.start_arrival(
            session_id=session_id,
            runway_id=payload.runway_id,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AtcDialogueResult(
        session_id=session_id,
        domain="arrival",
        language="en",
        intent="arrival_start",
        action="arrival_started",
        procedural_state=virtual_atc.status(session_id).procedural_state,
        reply="Arrival session started.",
        details={"arrival_state": session.state.value, "runway_id": session.runway_id},
    )


@router.post("/sessions/{session_id}/dialogue", response_model=AtcDialogueResult)
def handle_atc_dialogue(session_id: UUID, payload: AtcDialogueRequest) -> AtcDialogueResult:
    try:
        return atc_dialogue.handle(session_id, payload)
    except KeyError as exc:
        detail = "Airport arrival session not found" if "arrival" in str(exc).lower() else "ATC session not found"
        raise HTTPException(status_code=404, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
