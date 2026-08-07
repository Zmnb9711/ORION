from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orion.fa18c_calibration_wizard import CalibrationSession, hornet_calibration_wizard
from orion.fa18c_diagnostics_recorder import MappingReport, hornet_diagnostics_recorder


router = APIRouter(prefix="/fa18c/diagnostics", tags=["F/A-18C Diagnostics"])


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


@router.post("/calibration", response_model=CalibrationSession, status_code=201)
def start_calibration() -> CalibrationSession:
    return hornet_calibration_wizard.start()


@router.get("/calibration", response_model=CalibrationSession)
def get_calibration() -> CalibrationSession:
    try:
        return hornet_calibration_wizard.current()
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/calibration/evaluate", response_model=CalibrationSession)
def evaluate_calibration_step() -> CalibrationSession:
    try:
        return hornet_calibration_wizard.evaluate_step()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/calibration/retry", response_model=CalibrationSession)
def retry_calibration_step() -> CalibrationSession:
    try:
        return hornet_calibration_wizard.retry()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/calibration", status_code=204)
def cancel_calibration() -> None:
    hornet_calibration_wizard.cancel()
