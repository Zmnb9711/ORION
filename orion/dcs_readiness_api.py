from fastapi import APIRouter
from pydantic import BaseModel

from orion.dcs_connection_diagnostics import DcsConnectionReport, diagnose_dcs_connection
from orion.dcs_readiness import DcsReadinessReport, inspect_dcs_readiness, install_export_integration
from orion.preflight_orchestrator import PreflightReport, PreflightRequest, evaluate_preflight


router = APIRouter(prefix="/v1/dcs-readiness", tags=["DCS readiness"])


class ExportInstallRequest(BaseModel):
    saved_games_path: str


@router.get("", response_model=DcsReadinessReport)
def get_dcs_readiness(saved_games_path: str | None = None) -> DcsReadinessReport:
    return inspect_dcs_readiness(saved_games_path)


@router.get("/connection", response_model=DcsConnectionReport)
def get_dcs_connection() -> DcsConnectionReport:
    return diagnose_dcs_connection()


@router.post("/preflight", response_model=PreflightReport)
def get_preflight(payload: PreflightRequest) -> PreflightReport:
    return evaluate_preflight(payload)


@router.post("/export", response_model=DcsReadinessReport)
def install_dcs_export(payload: ExportInstallRequest) -> DcsReadinessReport:
    return install_export_integration(payload.saved_games_path)
