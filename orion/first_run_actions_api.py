from fastapi import APIRouter, Query

from orion.dcs_installations import DcsInstallationType
from orion.first_run_actions import (
    FirstRunActionResult,
    SelectActiveRequest,
    detect_installations,
    install_active_integration,
    select_active_installation,
    test_live_connection,
)


router = APIRouter(prefix="/v1/first-run/actions", tags=["First Run Wizard"])


@router.post("/detect", response_model=FirstRunActionResult)
def detect(mode: DcsInstallationType = Query(default=DcsInstallationType.AUTO)) -> FirstRunActionResult:
    return detect_installations(mode)


@router.post("/select-active", response_model=FirstRunActionResult)
def select_active(payload: SelectActiveRequest) -> FirstRunActionResult:
    return select_active_installation(payload)


@router.post("/install-integration", response_model=FirstRunActionResult)
def install_integration(saved_games_path: str | None = None) -> FirstRunActionResult:
    return install_active_integration(saved_games_path)


@router.post("/test-connection", response_model=FirstRunActionResult)
def test_connection() -> FirstRunActionResult:
    return test_live_connection()
