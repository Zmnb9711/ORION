from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orion.dcs_process import DcsProcessRecord, dcs_processes
from orion.flight_console import (
    FlightConsoleCreate,
    FlightConsoleState,
    flight_consoles,
)
from orion.flight_readiness import (
    FlightReadinessReport,
    FlightReadinessRequest,
    evaluate_flight_readiness,
)

router = APIRouter(prefix="/v1/dcs-processes", tags=["DCS processes"])


class DcsLaunchRequest(BaseModel):
    readiness: FlightReadinessRequest


class FlightLaunchRequest(DcsLaunchRequest):
    mission_name: str | None = None
    aircraft_name: str | None = None


class FlightLaunchResult(BaseModel):
    readiness: FlightReadinessReport
    process: DcsProcessRecord
    console: FlightConsoleState


def _evaluate_or_raise(payload: FlightReadinessRequest) -> FlightReadinessReport:
    try:
        report = evaluate_flight_readiness(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not report.ready_to_launch or report.launch_plan is None:
        failed = [check.message for check in report.checks if check.blocking and not check.passed]
        raise HTTPException(
            status_code=409,
            detail={"message": "DCS launch blocked", "checks": failed},
        )
    return report


def _start_process(profile_id: UUID, report: FlightReadinessReport) -> DcsProcessRecord:
    assert report.launch_plan is not None
    try:
        return dcs_processes.launch(profile_id, report.launch_plan)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/launch", response_model=DcsProcessRecord, status_code=201)
def launch_dcs(payload: DcsLaunchRequest) -> DcsProcessRecord:
    report = _evaluate_or_raise(payload.readiness)
    return _start_process(payload.readiness.profile_id, report)


@router.post("/launch-flight", response_model=FlightLaunchResult, status_code=201)
def launch_flight(payload: FlightLaunchRequest) -> FlightLaunchResult:
    """Launch DCS and create the matching Flight Console in one UI operation."""
    report = _evaluate_or_raise(payload.readiness)
    process = _start_process(payload.readiness.profile_id, report)

    mission_path = (
        report.launch_plan.mission_path
        if report.launch_plan is not None
        else payload.readiness.mission_path
    )
    console = flight_consoles.create(
        FlightConsoleCreate(
            launch_id=process.launch_id,
            profile_label=report.profile_label,
            mission_name=payload.mission_name,
            mission_path=mission_path,
            map_name=report.map_name,
            aircraft_name=payload.aircraft_name,
        )
    )
    return FlightLaunchResult(readiness=report, process=process, console=console)


@router.get("", response_model=list[DcsProcessRecord])
def list_dcs_processes() -> list[DcsProcessRecord]:
    return dcs_processes.list()


@router.get("/{launch_id}", response_model=DcsProcessRecord)
def get_dcs_process(launch_id: UUID) -> DcsProcessRecord:
    record = dcs_processes.get(launch_id)
    if record is None:
        raise HTTPException(status_code=404, detail="DCS launch record not found")
    return record
