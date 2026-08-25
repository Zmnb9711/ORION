"""Core API for explicit privacy-bounded realtime test evidence sessions."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.realtime_test_evidence import realtime_test_evidence


router = APIRouter(prefix="/v1/realtime/test-evidence", tags=["Realtime Test Evidence"])


class RealtimeTestEvidenceStart(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    transport: str = Field(min_length=1, max_length=40)


@router.post("/start")
def start_test_evidence(request: RealtimeTestEvidenceStart) -> dict[str, object]:
    try:
        return asdict(
            realtime_test_evidence.start(
                provider=request.provider,
                transport=request.transport,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status")
def test_evidence_status() -> dict[str, object]:
    return asdict(realtime_test_evidence.status())


@router.post("/stop-export")
def stop_and_export_test_evidence() -> dict[str, object]:
    try:
        output = realtime_test_evidence.stop_and_export()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"active": False, "export_path": str(output)}
