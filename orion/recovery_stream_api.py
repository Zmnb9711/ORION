from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from orion.recovery_presentation import RecoveryPresentation, RecoveryUiState, get_recovery_presentation


router = APIRouter()


def _format_state_event(presentation: RecoveryPresentation) -> str:
    payload = presentation.model_dump(mode="json")
    return (
        "event: recovery_state\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def _recovery_stream(
    request: Request,
    launch_id: UUID | None,
    language: str,
    heartbeat_seconds: float,
    poll_seconds: float,
) -> AsyncIterator[str]:
    last_signature: str | None = None
    elapsed = 0.0

    while not await request.is_disconnected():
        presentation = get_recovery_presentation(launch_id=launch_id, language=language)
        signature = presentation.model_dump_json(exclude={"health": {"checks"}})
        if signature != last_signature:
            yield _format_state_event(presentation)
            last_signature = signature
            elapsed = 0.0
            if presentation.state in {RecoveryUiState.READY, RecoveryUiState.FAILED}:
                return
        else:
            elapsed += poll_seconds
            if elapsed >= heartbeat_seconds:
                yield ": heartbeat\n\n"
                elapsed = 0.0
        await asyncio.sleep(poll_seconds)


@router.get("/stream")
def stream_recovery_ui(
    request: Request,
    launch_id: UUID | None = Query(default=None),
    language: str = Query(default="ru", pattern="^(ru|en)$"),
    heartbeat_seconds: float = Query(default=15.0, ge=1.0, le=60.0),
    poll_seconds: float = Query(default=0.5, ge=0.1, le=5.0),
) -> StreamingResponse:
    return StreamingResponse(
        _recovery_stream(request, launch_id, language, heartbeat_seconds, poll_seconds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
