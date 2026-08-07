from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orion.fa18c_diagnostics_recorder import MappingReport, hornet_diagnostics_recorder


router = APIRouter(prefix="/v1/fa18c/diagnostics", tags=["F/A-18C Diagnostics"])


class SessionStart(BaseModel):
    label: str | None = None


class SessionMarker(BaseModel):
    label: str | None = None


@router.post("/session", status_code=201)
def start_session(payload: SessionStart) -> dict[str, str]:
    return {"session_id": hornet_diagnostics_recorder.start(payload.label)}


@router.put("/session/marker")
def set_marker(payload: SessionMarker) -> dict[str, str | None]:
    try:
        hornet_diagnostics_recorder.mark(payload.label)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"marker": payload.label}


@router.get("/session/report", response_model=MappingReport)
def get_report() -> MappingReport:
    try:
        return hornet_diagnostics_recorder.report()
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/session/stop", response_model=MappingReport)
def stop_session() -> MappingReport:
    report = hornet_diagnostics_recorder.stop()
    if report is None:
        raise HTTPException(status_code=404, detail="No diagnostics session is active")
    return report


@router.delete("/session", status_code=204)
def clear_session() -> None:
    hornet_diagnostics_recorder.clear()
