from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.airport_atc_dialogue import AtcDialogueDomain, AtcDialogueRequest, AtcDialogueResult, airport_atc_dialogue
from orion.atc_service import AtcStatusSnapshot, virtual_atc
from orion.atc_simulator_sync import AtcIntegrationMode
from orion.dialogue import DialogueLanguage


router = APIRouter(prefix="/v1/atc", tags=["Virtual ATC"])

class AtcSessionBootstrapRequest(BaseModel):
    mission_id: str = Field(min_length=1, max_length=160)
    aircraft_id: str = Field(min_length=1, max_length=160)
    facility_id: str | None = Field(default=None, max_length=160)
    procedural_state: str = Field(default="atc_contact", min_length=1, max_length=160)
    integration_mode: AtcIntegrationMode = AtcIntegrationMode.ORION_PRIMARY


class AtcSessionBootstrapResult(BaseModel):
    created: bool
    status: AtcStatusSnapshot


class ArrivalStartRequest(BaseModel):
    runway_id: str = Field(min_length=1, max_length=40)
    reason: str = Field(default="arrival contact established", min_length=1, max_length=500)


@router.post("/sessions/bootstrap", response_model=AtcSessionBootstrapResult)
def bootstrap_atc_session(payload: AtcSessionBootstrapRequest) -> AtcSessionBootstrapResult:
    status, created = virtual_atc.get_or_open_session(
        mission_id=payload.mission_id,
        aircraft_id=payload.aircraft_id,
        facility_id=payload.facility_id,
        procedural_state=payload.procedural_state,
        integration_mode=payload.integration_mode,
    )
    return AtcSessionBootstrapResult(created=created, status=status)


@router.post("/sessions/{session_id}/arrival/start", response_model=AtcDialogueResult, status_code=201)
def start_arrival_session(session_id: UUID, payload: ArrivalStartRequest) -> AtcDialogueResult:
    try:
        virtual_atc.status(session_id)
        session = airport_atc_dialogue.arrival_orchestrator.start_arrival(
            session_id=session_id,
            runway_id=payload.runway_id,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AtcDialogueResult(session_id=session_id, domain=AtcDialogueDomain.ARRIVAL, language=DialogueLanguage.EN, intent="arrival_start", action="arrival_started", procedural_state=virtual_atc.status(session_id).procedural_state, reply="Arrival session started.", details={"arrival_state": session.state.value, "runway_id": session.runway_id})


@router.post("/sessions/{session_id}/dialogue", response_model=AtcDialogueResult)
def handle_atc_dialogue(session_id: UUID, payload: AtcDialogueRequest) -> AtcDialogueResult:
    try:
        return airport_atc_dialogue.handle(session_id, payload)
    except KeyError as exc:
        detail = "Airport arrival session not found" if "arrival" in str(exc).lower() else "ATC session not found"
        raise HTTPException(status_code=404, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
