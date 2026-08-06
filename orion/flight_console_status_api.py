from fastapi import APIRouter

from orion.flight_console_status import FlightConsoleStatus, flight_console_status


router = APIRouter(prefix="/v1/flight-console", tags=["Flight Console"])


@router.get("/status", response_model=FlightConsoleStatus)
def get_flight_console_status() -> FlightConsoleStatus:
    return flight_console_status.get_status()
