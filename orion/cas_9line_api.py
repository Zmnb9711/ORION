from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from orion.cas_9line import Cas9LineBrief, Cas9LineBriefCreate, Cas9LineReadback, Cas9LineReadbackResult, cas_9line_store
from orion.cas_9line_voice import submit_cas_9line_voice


router = APIRouter(prefix="/v1/mission-control/cas-9line", tags=["Mission Control", "CAS", "JTAC"])


@router.post("", response_model=Cas9LineBrief, status_code=201)
def create_brief(payload: Cas9LineBriefCreate) -> Cas9LineBrief:
    try:
        return cas_9line_store.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("", response_model=list[Cas9LineBrief])
def list_briefs() -> list[Cas9LineBrief]:
    return cas_9line_store.list()


@router.get("/{brief_id}", response_model=Cas9LineBrief)
def get_brief(brief_id: UUID) -> Cas9LineBrief:
    brief = cas_9line_store.get(brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="CAS 9-line brief not found")
    return brief


@router.post("/{brief_id}/issue", response_model=Cas9LineBrief)
def issue_brief(brief_id: UUID) -> Cas9LineBrief:
    try:
        brief = cas_9line_store.issue(brief_id)
        submit_cas_9line_voice(brief)
        return brief
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{brief_id}/readback", response_model=Cas9LineReadbackResult)
def verify_readback(brief_id: UUID, payload: Cas9LineReadback) -> Cas9LineReadbackResult:
    try:
        result = cas_9line_store.verify_readback_result(brief_id, payload)
        submit_cas_9line_voice(result.brief)
        return result
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{brief_id}/task", response_model=Cas9LineBrief, status_code=202)
def task_brief(brief_id: UUID) -> Cas9LineBrief:
    try:
        brief = cas_9line_store.task(brief_id)
        submit_cas_9line_voice(brief)
        return brief
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{brief_id}/abort", response_model=Cas9LineBrief)
def abort_brief(brief_id: UUID) -> Cas9LineBrief:
    try:
        brief = cas_9line_store.abort(brief_id)
        submit_cas_9line_voice(brief)
        return brief
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
