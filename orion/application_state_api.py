from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from orion.application_state import OrionApplicationState, get_application_state


router = APIRouter(prefix="/v1/application-state", tags=["ORION application state"])


@router.get("", response_model=OrionApplicationState)
def application_state() -> OrionApplicationState:
    return get_application_state()


def _format_state_event(state: OrionApplicationState) -> str:
    payload = state.model_dump(mode="json")
    return (
        "event: application_state\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def _application_state_stream(
    request: Request,
    heartbeat_seconds: float,
    poll_seconds: float,
) -> AsyncIterator[str]:
    last_signature: str | None = None
    elapsed = 0.0

    while not await request.is_disconnected():
        state = get_application_state()
        signature = state.model_dump_json()
        if signature != last_signature:
            yield _format_state_event(state)
            last_signature = signature
            elapsed = 0.0
        else:
            elapsed += poll_seconds
            if elapsed >= heartbeat_seconds:
                yield ": heartbeat\n\n"
                elapsed = 0.0
        await asyncio.sleep(poll_seconds)


@router.get("/stream")
def stream_application_state(
    request: Request,
    heartbeat_seconds: float = Query(default=15.0, ge=1.0, le=60.0),
    poll_seconds: float = Query(default=0.5, ge=0.1, le=5.0),
) -> StreamingResponse:
    return StreamingResponse(
        _application_state_stream(request, heartbeat_seconds, poll_seconds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
