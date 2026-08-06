from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.official_knowledge_retrieval import (
    FragmentRequest,
    RetrievedFragment,
    RetrievalState,
    knowledge_retrieval,
)

router = APIRouter(prefix="/v1/knowledge-manager/retrievals", tags=["Knowledge Manager"])


class RetrievalStateUpdate(BaseModel):
    state: RetrievalState


class RetrievalCompletion(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    size_bytes: int = Field(ge=0)


class RetrievalFailure(BaseModel):
    error: str = Field(min_length=1, max_length=2000)


@router.get("", response_model=list[RetrievedFragment])
def list_retrievals() -> list[RetrievedFragment]:
    return knowledge_retrieval.list()


@router.post("", response_model=RetrievedFragment, status_code=202)
def request_fragment(payload: FragmentRequest) -> RetrievedFragment:
    try:
        return knowledge_retrieval.request(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{request_id}", response_model=RetrievedFragment)
def get_retrieval(request_id: UUID) -> RetrievedFragment:
    item = knowledge_retrieval.get(request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Retrieval request not found")
    return item


@router.put("/{request_id}/state", response_model=RetrievedFragment)
def update_retrieval_state(request_id: UUID, payload: RetrievalStateUpdate) -> RetrievedFragment:
    try:
        return knowledge_retrieval.set_state(request_id, payload.state)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Retrieval request not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{request_id}/complete", response_model=RetrievedFragment)
def complete_retrieval(request_id: UUID, payload: RetrievalCompletion) -> RetrievedFragment:
    try:
        return knowledge_retrieval.complete(request_id, text=payload.text, size_bytes=payload.size_bytes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Retrieval request not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{request_id}/fail", response_model=RetrievedFragment)
def fail_retrieval(request_id: UUID, payload: RetrievalFailure) -> RetrievedFragment:
    try:
        return knowledge_retrieval.fail(request_id, payload.error)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Retrieval request not found") from exc


@router.post("/{request_id}/cancel", response_model=RetrievedFragment)
def cancel_retrieval(request_id: UUID) -> RetrievedFragment:
    try:
        return knowledge_retrieval.cancel(request_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Retrieval request not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
