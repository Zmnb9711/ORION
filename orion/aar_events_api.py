from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orion.aar_events import AarEvent, AarEventResult, aar_events


router = APIRouter(prefix="/v1/aar/events", tags=["AAR events"])


@router.post("", response_model=AarEventResult, status_code=202)
def ingest_aar_event(event: AarEvent) -> AarEventResult:
    result = aar_events.ingest(event)
    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.message)
    return result


@router.get("", response_model=list[AarEvent])
def list_aar_events() -> list[AarEvent]:
    return aar_events.list()
