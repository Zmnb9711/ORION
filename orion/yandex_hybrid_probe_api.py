"""Core API for the opt-in IA-1.1 hybrid presentation probe."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orion.yandex_hybrid_probe import AcousticReview, yandex_hybrid_probe

router = APIRouter(prefix="/v1/realtime/yandex/hybrid-presentation-probe", tags=["Realtime Voice"])


class HybridProbeStart(BaseModel):
    capture_synthetic_audio: bool = False


class HybridProbeReview(BaseModel):
    result: AcousticReview


@router.post("/start")
def start_hybrid_probe(request: HybridProbeStart) -> dict[str, object]:
    try:
        status = yandex_hybrid_probe.start(capture_audio=request.capture_synthetic_audio)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return status.model_dump(mode="json")


@router.get("/status")
def hybrid_probe_status() -> dict[str, object]:
    return yandex_hybrid_probe.status().model_dump(mode="json")


@router.post("/review")
def review_hybrid_probe(request: HybridProbeReview) -> dict[str, object]:
    try:
        status = yandex_hybrid_probe.review(request.result)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return status.model_dump(mode="json")
