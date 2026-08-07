from fastapi import APIRouter

from orion.dcs_connection_diagnostics import DcsConnectionReport, diagnose_dcs_connection


router = APIRouter(prefix="/v1/dcs-connection", tags=["DCS connection"])


@router.get("/diagnostics", response_model=DcsConnectionReport)
def get_dcs_connection_diagnostics() -> DcsConnectionReport:
    return diagnose_dcs_connection()
