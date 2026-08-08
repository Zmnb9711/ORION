from fastapi import APIRouter

from orion.startup_health import StartupHealthReport, inspect_startup_health


router = APIRouter(prefix="/v1/startup-health", tags=["Startup health"])


@router.get("", response_model=StartupHealthReport)
def startup_health() -> StartupHealthReport:
    return inspect_startup_health()
