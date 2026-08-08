from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from orion.jtac_runtime import JtacSession, JtacSessionCreate, jtac_sessions
from orion.jtac_voice import submit_jtac_voice


router = APIRouter(prefix="/v1/jtac", tags=["JTAC"])


@router.post("/sessions", response_model=JtacSession, status_code=201)
def create_jtac_session(payload: JtacSessionCreate, speak: bool = Query(default=False), language: str = Query(default="en")) -> JtacSession:
    try:
        session = jtac_sessions.create(payload, language=language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if speak:
        submit_jtac_voice(session, language)
    return session


@router.get("/sessions", response_model=list[JtacSession])
def list_jtac_sessions() -> list[JtacSession]:
    return jtac_sessions.list()


@router.get("/sessions/{session_id}", response_model=JtacSession)
def get_jtac_session(session_id: UUID, reconcile: bool = Query(default=True), speak: bool = Query(default=False), language: str = Query(default="en")) -> JtacSession:
    try:
        session = jtac_sessions.reconcile(session_id) if reconcile else jtac_sessions.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="JTAC session not found")
    if speak:
        submit_jtac_voice(session, language)
    return session


@router.post("/sessions/{session_id}/mark", response_model=JtacSession)
def start_jtac_marking(session_id: UUID) -> JtacSession:
    try:
        return jtac_sessions.start_marking(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/reconcile", response_model=JtacSession)
def reconcile_jtac_session(session_id: UUID, speak: bool = Query(default=True), language: str | None = Query(default=None)) -> JtacSession:
    try:
        session = jtac_sessions.reconcile(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if speak:
        submit_jtac_voice(session, language or session.language)
    return session
