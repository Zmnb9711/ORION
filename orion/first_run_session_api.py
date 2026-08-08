from fastapi import APIRouter, Query

from orion.dcs_installations import DcsInstallationType
from orion.first_run_session import FirstRunSessionState, get_first_run_session


router = APIRouter(prefix="/v1/first-run", tags=["First Run Wizard"])


@router.get("/session", response_model=FirstRunSessionState)
def first_run_session(
    mode: DcsInstallationType = Query(default=DcsInstallationType.AUTO),
) -> FirstRunSessionState:
    return get_first_run_session(mode)
