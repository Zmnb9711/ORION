import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from orion.flight_console import (
    FlightConsoleCreate,
    FlightConsoleState,
    FlightConsoleUpdate,
    flight_consoles,
)
from orion.flight_console_events import FlightConsoleEvent, flight_console_events

router = APIRouter(prefix="/v1/flight-console", tags=["Flight Console"])


@router.post("", response_model=FlightConsoleState, status_code=201)
def create_flight_console(payload: FlightConsoleCreate) -> FlightConsoleState:
    try:
        return flight_consoles.create(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[FlightConsoleState])
def list_flight_consoles() -> list[FlightConsoleState]:
    return flight_consoles.list()


@router.get("/events", response_model=list[FlightConsoleEvent])
def read_flight_console_events(
    after: int = Query(default=0, ge=0),
    launch_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[FlightConsoleEvent]:
    return flight_console_events.read_after(
        sequence=after,
        launch_id=launch_id,
        limit=limit,
    )


def _format_sse(event: FlightConsoleEvent) -> str:
    payload = event.model_dump(mode="json")
    return (
        f"id: {event.sequence}\n"
        f"event: {event.event_type}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def _event_stream(
    request: Request,
    after: int,
    launch_id: UUID | None,
    heartbeat_seconds: float,
) -> AsyncIterator[str]:
    cursor = after
    elapsed = 0.0
    interval = min(0.5, heartbeat_seconds)

    while not await request.is_disconnected():
        events = flight_console_events.read_after(
            sequence=cursor,
            launch_id=launch_id,
            limit=100,
        )
        if events:
            for event in events:
                cursor = max(cursor, event.sequence)
                yield _format_sse(event)
            elapsed = 0.0
        else:
            await asyncio.sleep(interval)
            elapsed += interval
            if elapsed >= heartbeat_seconds:
                yield ": heartbeat\n\n"
                elapsed = 0.0


@router.get("/stream")
def stream_flight_console_events(
    request: Request,
    after: int = Query(default=0, ge=0),
    launch_id: UUID | None = Query(default=None),
    heartbeat_seconds: float = Query(default=15.0, ge=1.0, le=60.0),
) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(request, after, launch_id, heartbeat_seconds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{launch_id}", response_model=FlightConsoleState)
def get_flight_console(launch_id: UUID) -> FlightConsoleState:
    state = flight_consoles.get(launch_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Flight Console not found")
    return state


@router.patch("/{launch_id}", response_model=FlightConsoleState)
def update_flight_console(
    launch_id: UUID, payload: FlightConsoleUpdate
) -> FlightConsoleState:
    state = flight_consoles.update(launch_id, payload)
    if state is None:
        raise HTTPException(status_code=404, detail="Flight Console not found")
    return state
