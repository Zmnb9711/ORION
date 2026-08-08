from fastapi import APIRouter
from pydantic import BaseModel

from orion.active_dcs_installation import active_dcs_installation
from orion.dcs_connection_diagnostics import DcsConnectionReport, diagnose_dcs_connection
from orion.dcs_readiness import DcsReadinessReport, inspect_dcs_readiness, install_export_integration
from orion.fa18c_calibration_wizard import CalibrationSession, CalibrationStatus, hornet_calibration_wizard
from orion.preflight_orchestrator import PreflightReport, PreflightRequest, PreflightState, evaluate_preflight


router = APIRouter(prefix="/v1/dcs-readiness", tags=["DCS readiness"])


class ExportInstallRequest(BaseModel):
    saved_games_path: str | None = None


class PreflightBootstrapResult(BaseModel):
    preflight: PreflightReport
    calibration: CalibrationSession | None = None


def _resolved_saved_games(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    active = active_dcs_installation.get()
    return active.saved_games_path if active is not None else None


@router.get("", response_model=DcsReadinessReport)
def get_dcs_readiness(saved_games_path: str | None = None) -> DcsReadinessReport:
    return inspect_dcs_readiness(_resolved_saved_games(saved_games_path))


@router.get("/connection", response_model=DcsConnectionReport)
def get_dcs_connection() -> DcsConnectionReport:
    return diagnose_dcs_connection()


@router.post("/preflight", response_model=PreflightReport)
def get_preflight(payload: PreflightRequest) -> PreflightReport:
    return evaluate_preflight(payload)


@router.post("/preflight/bootstrap", response_model=PreflightBootstrapResult)
def bootstrap_preflight(payload: PreflightRequest) -> PreflightBootstrapResult:
    report = evaluate_preflight(payload)
    calibration: CalibrationSession | None = None
    if report.state is PreflightState.CALIBRATION_REQUIRED:
        try:
            current = hornet_calibration_wizard.current()
        except RuntimeError:
            current = None
        if current is not None and current.status in {CalibrationStatus.RUNNING, CalibrationStatus.NEEDS_RETRY}:
            calibration = current
        else:
            calibration = hornet_calibration_wizard.start()
    return PreflightBootstrapResult(preflight=report, calibration=calibration)


@router.post("/export", response_model=DcsReadinessReport)
def install_dcs_export(payload: ExportInstallRequest) -> DcsReadinessReport:
    saved_games = _resolved_saved_games(payload.saved_games_path)
    if not saved_games:
        return inspect_dcs_readiness()
    return install_export_integration(saved_games)
