from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from orion.fa18c_calibration_wizard import CalibrationSession, hornet_calibration_wizard


router = APIRouter(prefix="/fa18c/calibration", tags=["F/A-18C Calibration Wizard"])


@router.post("/session", response_model=CalibrationSession, status_code=201)
def start_calibration() -> CalibrationSession:
    return hornet_calibration_wizard.start()


@router.get("/session", response_model=CalibrationSession)
def get_calibration() -> CalibrationSession:
    try:
        return hornet_calibration_wizard.current()
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/session/evaluate", response_model=CalibrationSession)
def evaluate_step(minimum_confidence: float = Query(default=0.72, ge=0, le=1)) -> CalibrationSession:
    try:
        return hornet_calibration_wizard.evaluate_step(minimum_confidence)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/session/retry", response_model=CalibrationSession)
def retry_step() -> CalibrationSession:
    try:
        return hornet_calibration_wizard.retry()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/session", status_code=204)
def cancel_calibration() -> None:
    hornet_calibration_wizard.cancel()
