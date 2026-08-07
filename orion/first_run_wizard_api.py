from fastapi import APIRouter

from orion.first_run_wizard import FirstRunReport, FirstRunRequest, evaluate_first_run
from orion.telemetry_handshake import telemetry_handshake


router = APIRouter(prefix="/v1/first-run", tags=["First Run Wizard"])


@router.post("/status", response_model=FirstRunReport)
def first_run_status(payload: FirstRunRequest) -> FirstRunReport:
    if payload.telemetry_received is None:
        live = telemetry_handshake.snapshot()
        payload = payload.model_copy(
            update={
                "telemetry_received": live.connected,
                "aircraft_type": live.aircraft_type if live.connected else None,
            }
        )
    return evaluate_first_run(payload)
