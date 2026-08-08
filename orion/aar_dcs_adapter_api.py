from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orion.aar_dcs_adapter import AarAdapterResult, AarRawObservation, aar_dcs_adapter


router = APIRouter(prefix="/v1/aar/raw-observations", tags=["AAR DCS adapter"])


@router.post("", response_model=AarAdapterResult, status_code=202)
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
