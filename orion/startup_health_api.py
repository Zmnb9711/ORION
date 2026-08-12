from fastapi import APIRouter

from orion.dcs_connection_diagnostics import DcsConnectionReport, diagnose_dcs_connection
from orion.startup_health import StartupHealthReport, inspect_startup_health


router = APIRouter(tags=["Startup health"])


@router.get("/v1/startup-health", response_model=StartupHealthReport)
def startup_health() -> StartupHealthReport:
    return inspect_startup_health()


@router.get("/v1/dcs-connection/diagnostics", response_model=DcsConnectionReport, tags=["DCS connection"])
def dcs_connection_diagnostics() -> DcsConnectionReport:
    return diagnose_dcs_connection()
