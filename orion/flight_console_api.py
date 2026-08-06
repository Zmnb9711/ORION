from uuid import UUID

from fastapi import APIRouter, HTTPException

from orion.flight_console import (
    FlightConsoleCreate,
    FlightConsoleState,
    FlightConsoleUpdate,
    flight_consoles,
)

router = APIRouter(prefix="/v1/flight-console", tags=["Flight Console"])


@router.post("", response_model=FlightConsoleState, status_code=201)
def create_flight_console(payload: FlightConsoleCreate) -> FlightConsoleState:
    try:
        return flight_consoles.create(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[FlightConsoleState])
def list_flight_consoles() -> list[FlightConsoleState]:
    return flight_consoles.list()


@router.get("/{launch_id}", response_model=FlightConsoleState)
def get_flight_console(launch_id: UUID) -> FlightConsoleState:
    state = flight_consoles.get(launch_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Flight Console not found")
    return state


@router.patch("/{launch_id}", response_model=FlightConsoleState)
def update_flight_console(
    launch_id: UUID, payload: FlightConsoleUpdate
) -> FlightConsoleState:
    state = flight_consoles.update(launch_id, payload)
    if state is None:
        raise HTTPException(status_code=404, detail="Flight Console not found")
    return state
