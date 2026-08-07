from fastapi import APIRouter

from orion.preflight_orchestrator import PreflightReport, PreflightRequest, evaluate_preflight


router = APIRouter(prefix="/v1/preflight", tags=["Preflight"])


@router.post("/status", response_model=PreflightReport)
def preflight_status(payload: PreflightRequest) -> PreflightReport:
    return evaluate_preflight(payload)
