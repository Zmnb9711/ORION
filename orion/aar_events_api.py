from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orion.aar_dcs_adapter import AarAdapterResult, AarRawObservation, aar_dcs_adapter
from orion.aar_events import AarEvent, AarEventResult, aar_events


router = APIRouter(prefix="/v1/aar", tags=["AAR events"])


@router.post("/events", response_model=AarEventResult, status_code=202)
def ingest_aar_event(event: AarEvent) -> AarEventResult:
    result = aar_events.ingest(event)
    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.message)
    return result


@router.get("/events", response_model=list[AarEvent])
def list_aar_events() -> list[AarEvent]:
    return aar_events.list()


@router.post("/raw-observations", response_model=AarAdapterResult, status_code=202)
def ingest_raw_aar_observation(observation: AarRawObservation) -> AarAdapterResult:
    result = aar_dcs_adapter.ingest(observation)
    rejected = [item for item in result.event_results if not item.accepted]
    if rejected:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "One or more normalized AAR events were rejected",
                "reasons": [item.message for item in rejected],
            },
        )
    return result
