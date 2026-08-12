from fastapi import APIRouter

from orion.dcs_connection_diagnostics import DcsConnectionReport, _diagnose_dcs_connection_local, detect_dcs_process
from orion.startup_health import StartupHealthReport, inspect_startup_health
from orion.telemetry_handshake import telemetry_handshake


router = APIRouter(tags=["Startup health"])


@router.get("/v1/startup-health", response_model=StartupHealthReport)
def startup_health() -> StartupHealthReport:
    return inspect_startup_health()


@router.get("/v1/dcs-connection/diagnostics", response_model=DcsConnectionReport, tags=["DCS connection"])
def dcs_connection_diagnostics() -> DcsConnectionReport:
    return _diagnose_dcs_connection_local(
        handshake=telemetry_handshake,
        process_detector=detect_dcs_process,
        minimum_healthy_rate_hz=5.0,
    )
