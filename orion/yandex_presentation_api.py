"""Core API for the bounded IA-1 Yandex presentation probe."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orion.yandex_presentation import ProbeSelection, yandex_presentation


router = APIRouter(prefix="/v1/realtime/yandex/presentation-probe", tags=["Realtime Voice"])


class PresentationProbeStart(BaseModel):
    selection: ProbeSelection = ProbeSelection.FULL


@router.post("/start")
def start_presentation_probe(request: PresentationProbeStart) -> dict[str, object]:
    try:
        status = yandex_presentation.start(request.selection)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return status.model_dump(mode="json")


@router.get("/status")
def presentation_probe_status() -> dict[str, object]:
    return yandex_presentation.status().model_dump(mode="json")
