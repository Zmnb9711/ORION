from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from orion.assistant_messages import (
    AssistantMessage,
    AssistantMessageCreate,
    AssistantMessageState,
    assistant_messages,
)

router = APIRouter(prefix="/v1/assistant-messages", tags=["Assistant Messages"])


@router.get("", response_model=list[AssistantMessage])
def list_messages(state: AssistantMessageState | None = None) -> list[AssistantMessage]:
    return assistant_messages.list(state=state)


@router.post("", response_model=AssistantMessage, status_code=201)
def enqueue_message(payload: AssistantMessageCreate) -> AssistantMessage:
    return assistant_messages.enqueue(payload)


@router.get("/{message_id}", response_model=AssistantMessage)
def get_message(message_id: UUID) -> AssistantMessage:
    item = assistant_messages.get(message_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Assistant message not found")
    return item


@router.post("/claim-next", response_model=AssistantMessage | None)
def claim_next_message(
    consumer: str = Query(min_length=1, max_length=120),
    speech_only: bool = False,
) -> AssistantMessage | None:
    return assistant_messages.claim_next(consumer, speech_only=speech_only)


@router.post("/{message_id}/delivered", response_model=AssistantMessage)
def mark_message_delivered(message_id: UUID, consumer: str = Query(min_length=1, max_length=120)) -> AssistantMessage:
    try:
        return assistant_messages.delivered(message_id, consumer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Assistant message not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{message_id}/release", response_model=AssistantMessage)
def release_message(
    message_id: UUID,
    consumer: str = Query(min_length=1, max_length=120),
    error: str | None = Query(default=None, max_length=2000),
) -> AssistantMessage:
    try:
        return assistant_messages.release(message_id, consumer, error=error)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Assistant message not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{message_id}/fail", response_model=AssistantMessage)
def fail_message(message_id: UUID, error: str = Query(min_length=1, max_length=2000)) -> AssistantMessage:
    try:
        return assistant_messages.fail(message_id, error)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Assistant message not found") from exc


@router.post("/{message_id}/cancel", response_model=AssistantMessage)
def cancel_message(message_id: UUID) -> AssistantMessage:
    try:
        return assistant_messages.cancel(message_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Assistant message not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
