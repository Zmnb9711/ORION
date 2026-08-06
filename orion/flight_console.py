from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, Field

from orion.dcs_process import ProcessState, dcs_processes


class FlightConsoleCreate(BaseModel):
    launch_id: UUID
    profile_label: str
    mission_name: str | None = None
    mission_path: str | None = None
    map_name: str | None = None
    aircraft_name: str | None = None


class FlightConsoleUpdate(BaseModel):
    ai_ready: bool | None = None
    flight_bridge_connected: bool | None = None
    mission_bridge_connected: bool | None = None
    mission_pack_connected: bool | None = None
    voice_active: bool | None = None
    last_command: str | None = None
    last_command_status: str | None = None
    last_message: str | None = None


class FlightConsoleState(BaseModel):
    launch_id: UUID
    profile_label: str
    mission_name: str | None = None
    mission_path: str | None = None
    map_name: str | None = None
    aircraft_name: str | None = None
    dcs_pid: int
    dcs_running: bool = True
    dcs_exit_code: int | None = None
    ai_ready: bool = True
    flight_bridge_connected: bool = False
    mission_bridge_connected: bool = False
    mission_pack_connected: bool = False
    voice_active: bool = False
    last_command: str | None = None
    last_command_status: str | None = None
    last_message: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def ai_status(self) -> str:
        return "AI готов" if self.ai_ready else "AI не готов"


class FlightConsoleStore:
    def __init__(self) -> None:
        self._states: dict[UUID, FlightConsoleState] = {}
        self._lock = RLock()

    def create(self, payload: FlightConsoleCreate) -> FlightConsoleState:
        process = dcs_processes.get(payload.launch_id)
        if process is None:
            raise KeyError("DCS launch not found")
        state = FlightConsoleState(
            **payload.model_dump(),
            dcs_pid=process.pid,
            dcs_running=process.state is ProcessState.STARTED,
            dcs_exit_code=process.exit_code,
        )
        with self._lock:
            self._states[payload.launch_id] = state
        return state

    def get(self, launch_id: UUID) -> FlightConsoleState | None:
        with self._lock:
            current = self._states.get(launch_id)
            if current is None:
                return None
            process = dcs_processes.get(launch_id)
            updates: dict[str, object] = {"updated_at": datetime.now(UTC)}
            if process is not None:
                updates.update(
                    dcs_pid=process.pid,
                    dcs_running=process.state is ProcessState.STARTED,
                    dcs_exit_code=process.exit_code,
                )
            current = current.model_copy(update=updates)
            self._states[launch_id] = current
            return current

    def update(self, launch_id: UUID, payload: FlightConsoleUpdate) -> FlightConsoleState | None:
        with self._lock:
            current = self._states.get(launch_id)
            if current is None:
                return None
            updates = payload.model_dump(exclude_none=True)
            updates["updated_at"] = datetime.now(UTC)
            current = current.model_copy(update=updates)
            self._states[launch_id] = current
        return self.get(launch_id)

    def list(self) -> list[FlightConsoleState]:
        with self._lock:
            launch_ids = list(self._states)
        return [state for launch_id in launch_ids if (state := self.get(launch_id)) is not None]


flight_consoles = FlightConsoleStore()
