from fastapi import APIRouter

from orion.first_run_wizard import FirstRunReport, FirstRunRequest, evaluate_first_run


router = APIRouter(prefix="/v1/first-run", tags=["First Run Wizard"])


@router.post("/status", response_model=FirstRunReport)
def first_run_status(payload: FirstRunRequest) -> FirstRunReport:
    return evaluate_first_run(payload)
