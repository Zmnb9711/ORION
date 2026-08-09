from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from orion.atc_service import AtcStatusSnapshot, virtual_atc


router = APIRouter(prefix="/v1/atc", tags=["Virtual ATC"])


@router.get("/sessions/{session_id}/status", response_model=AtcStatusSnapshot)
def get_atc_session_status(session_id: UUID) -> AtcStatusSnapshot:
    try:
        return virtual_atc.status(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC session not found") from exc


@router.delete("/sessions/{session_id}", status_code=204)
def close_atc_session(session_id: UUID) -> None:
    try:
        virtual_atc.close_session(session_id, reason="ATC session closed via API")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ATC session not found") from exc
