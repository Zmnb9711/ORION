"""Core API for the bounded Live Golden Conversation field session."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orion.live_golden_conversation import (
    InformationalPresentationBackend,
    LiveGoldenAcousticReview,
    live_golden_conversation,
)


router = APIRouter(
    prefix="/v1/realtime/live-golden-conversation",
    tags=["Live Golden Conversation"],
)


class LiveGoldenStart(BaseModel):
    capture_response_audio: bool = True
    informational_backend: InformationalPresentationBackend = (
        InformationalPresentationBackend.CURRENT_QWEN
    )


class LiveGoldenReview(BaseModel):
    result: LiveGoldenAcousticReview


@router.post("/start")
def start_live_golden(request: LiveGoldenStart) -> dict[str, object]:
    try:
        return live_golden_conversation.start(
            capture_audio=request.capture_response_audio,
            informational_backend=request.informational_backend,
        ).model_dump(mode="json")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status")
def live_golden_status() -> dict[str, object]:
    return live_golden_conversation.status().model_dump(mode="json")


@router.post("/review")
def review_live_golden(request: LiveGoldenReview) -> dict[str, object]:
    try:
        return live_golden_conversation.review(request.result).model_dump(mode="json")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/stop")
def stop_live_golden() -> dict[str, object]:
    return live_golden_conversation.stop().model_dump(mode="json")
