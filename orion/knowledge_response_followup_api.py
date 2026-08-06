from uuid import UUID

from fastapi import APIRouter, HTTPException

from orion.knowledge_response_followup import (
    KnowledgeFollowUp,
    KnowledgeFollowUpCreate,
    knowledge_follow_ups,
)

router = APIRouter(prefix="/v1/knowledge-manager/follow-ups", tags=["Knowledge Manager"])


@router.get("", response_model=list[KnowledgeFollowUp])
def list_follow_ups(ready_only: bool = False) -> list[KnowledgeFollowUp]:
    return knowledge_follow_ups.list(ready_only=ready_only)


@router.post("", response_model=KnowledgeFollowUp, status_code=201)
def register_follow_up(payload: KnowledgeFollowUpCreate) -> KnowledgeFollowUp:
    try:
        return knowledge_follow_ups.register(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{follow_up_id}", response_model=KnowledgeFollowUp)
def get_follow_up(follow_up_id: UUID) -> KnowledgeFollowUp:
    item = knowledge_follow_ups.get(follow_up_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge follow-up not found")
    return item


@router.post("/{follow_up_id}/refresh", response_model=KnowledgeFollowUp)
def refresh_follow_up(follow_up_id: UUID, language: str = "ru") -> KnowledgeFollowUp:
    try:
        return knowledge_follow_ups.refresh(follow_up_id, language=language)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{follow_up_id}/delivered", response_model=KnowledgeFollowUp)
def mark_follow_up_delivered(follow_up_id: UUID) -> KnowledgeFollowUp:
    try:
        return knowledge_follow_ups.mark_delivered(follow_up_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
