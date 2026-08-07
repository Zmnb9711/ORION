from fastapi import APIRouter, HTTPException

from orion.flight_readiness import (
    FlightReadinessReport,
    FlightReadinessRequest,
    evaluate_flight_readiness,
)

router = APIRouter(prefix="/v1/flight-readiness", tags=["flight-readiness"])


@router.post("/evaluate", response_model=FlightReadinessReport)
def evaluate(payload: FlightReadinessRequest) -> FlightReadinessReport:
    try:
        return evaluate_flight_readiness(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
