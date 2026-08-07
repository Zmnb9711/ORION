from fastapi import APIRouter
from pydantic import BaseModel

from orion.dcs_readiness import DcsReadinessReport, inspect_dcs_readiness, install_export_integration


router = APIRouter(prefix="/v1/dcs-readiness", tags=["DCS readiness"])


class ExportInstallRequest(BaseModel):
    saved_games_path: str


@router.get("", response_model=DcsReadinessReport)
def get_dcs_readiness(saved_games_path: str | None = None) -> DcsReadinessReport:
    return inspect_dcs_readiness(saved_games_path)


@router.post("/export", response_model=DcsReadinessReport)
def install_dcs_export(payload: ExportInstallRequest) -> DcsReadinessReport:
    return install_export_integration(payload.saved_games_path)
