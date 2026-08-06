from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orion.dcs_process import DcsProcessRecord, dcs_processes
from orion.flight_readiness import FlightReadinessRequest, evaluate_flight_readiness

router = APIRouter(prefix="/v1/dcs-processes", tags=["DCS processes"])


class DcsLaunchRequest(BaseModel):
    readiness: FlightReadinessRequest


@router.post("/launch", response_model=DcsProcessRecord, status_code=201)
def launch_dcs(payload: DcsLaunchRequest) -> DcsProcessRecord:
    try:
        report = evaluate_flight_readiness(payload.readiness)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not report.ready_to_launch or report.launch_plan is None:
        failed = [check.message for check in report.checks if check.blocking and not check.passed]
        raise HTTPException(status_code=409, detail={"message": "DCS launch blocked", "checks": failed})

    try:
        return dcs_processes.launch(payload.readiness.profile_id, report.launch_plan)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("", response_model=list[DcsProcessRecord])
def list_dcs_processes() -> list[DcsProcessRecord]:
    return dcs_processes.list()


@router.get("/{launch_id}", response_model=DcsProcessRecord)
def get_dcs_process(launch_id: UUID) -> DcsProcessRecord:
    record = dcs_processes.get(launch_id)
    if record is None:
        raise HTTPException(status_code=404, detail="DCS launch record not found")
    return record
