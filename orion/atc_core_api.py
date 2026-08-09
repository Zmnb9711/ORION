from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.atc_core import (
    ControllerAgency,
    ControllerAuthorityScope,
    ControllerHandoffTransaction,
)
from orion.atc_service import AtcStatusSnapshot, virtual_atc
from orion.atc_simulator_sync import AtcIntegrationMode


router = APIRouter(prefix="/v1/atc", tags=["Virtual ATC"])


class EventGatedHandoffCreate(BaseModel):
    session_id: UUID
    source: ControllerAgency
    destination: ControllerAgency
    scopes: list[ControllerAuthorityScope] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)
    frequency: str | None = Field(default=None, max_length=80)
    channel: str | None = Field(default=None, max_length=80)


class EventGatedHandoffComplete(BaseModel):
    event_name: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)
    contact_established: bool | None = None


class IntegrationModeChange(BaseModel):
    mode: AtcIntegrationMode
    reason: str = Field(min_length=1, max_length=500)


class IntegrationModeSnapshot(BaseModel):
    session_id: UUID
    mode: AtcIntegrationMode


@router.get("/sessions/{session_id}/status", response_model=AtcStatusSnapshot)
def get_atc_session_status(session_id: UUID) -> AtcStatusSnapshot:
    try:
        return virtual_atc.status(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC session not found") from exc


@router.get("/sessions/{session_id}/integration", response_model=IntegrationModeSnapshot)
def get_atc_integration_mode(session_id: UUID) -> IntegrationModeSnapshot:
    try:
        mode = virtual_atc.get_integration_mode(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC session not found") from exc
    return IntegrationModeSnapshot(session_id=session_id, mode=mode)


@router.put("/sessions/{session_id}/integration", response_model=IntegrationModeSnapshot)
def set_atc_integration_mode(
    session_id: UUID,
    payload: IntegrationModeChange,
) -> IntegrationModeSnapshot:
    try:
        mode = virtual_atc.set_integration_mode(session_id, payload.mode, reason=payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC session not found") from exc
    return IntegrationModeSnapshot(session_id=session_id, mode=mode)


@router.post("/handoffs/event-gated", response_model=ControllerHandoffTransaction, status_code=201)
def create_event_gated_handoff(payload: EventGatedHandoffCreate) -> ControllerHandoffTransaction:
    try:
        return virtual_atc.begin_event_gated_handoff(
            session_id=payload.session_id,
            source=payload.source,
            destination=payload.destination,
            scopes=payload.scopes,
            reason=payload.reason,
            frequency=payload.frequency,
            channel=payload.channel,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/handoffs/{handoff_id}", response_model=ControllerHandoffTransaction)
def get_atc_handoff(handoff_id: UUID) -> ControllerHandoffTransaction:
    handoff = virtual_atc.core.authority.get_handoff(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="ATC handoff not found")
    return handoff


@router.post("/handoffs/{handoff_id}/event", response_model=ControllerHandoffTransaction)
def complete_event_gated_handoff(
    handoff_id: UUID,
    payload: EventGatedHandoffComplete,
) -> ControllerHandoffTransaction:
    try:
        return virtual_atc.complete_event_gated_handoff(
            handoff_id,
            event_name=payload.event_name,
            reason=payload.reason,
            contact_established=payload.contact_established,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC handoff or session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=204)
def close_atc_session(session_id: UUID) -> None:
    try:
        virtual_atc.close_session(session_id, reason="ATC session closed via API")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC session not found") from exc
