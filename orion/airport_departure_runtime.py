from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.airport_tower_runtime import AirportTowerController
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import AcknowledgementState, OperationalInstruction


class AirportDepartureState(StrEnum):
    HOLDING_POINT = "holding_point"
    LINE_UP_CLEARED = "line_up_cleared"
    LINED_UP = "lined_up"
    TAKEOFF_CLEARED = "takeoff_cleared"
    TAKEOFF_ROLL = "takeoff_roll"
    AIRBORNE = "airborne"
    DEPARTURE_CONTROL = "departure_control"
    REJECTED_TAKEOFF = "rejected_takeoff"


class AirportDepartureSession(BaseModel):
    session_id: UUID
    runway_id: str
    state: AirportDepartureState = AirportDepartureState.HOLDING_POINT
    line_up_instruction_id: UUID | None = None
    takeoff_instruction_id: UUID | None = None
    departure_handoff_id: UUID | None = None


class AirportDepartureRuntime:
    """Departure procedure from holding point through confirmed airborne handoff."""

    def __init__(self, surface: AirportSurfaceCoordinator | None = None) -> None:
        self.surface = surface or AirportSurfaceCoordinator()
        self.core = self.surface.core
        self.tower = AirportTowerController(self.surface)
        self._sessions: dict[UUID, AirportDepartureSession] = {}

    def start(self, *, session_id: UUID, runway_id: str) -> AirportDepartureSession:
        if session_id in self._sessions:
            raise ValueError("Departure session already exists")
        tower_owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.LANDING_AREA)
        if tower_owner is None or tower_owner.agency is not ControllerAgency.AIRPORT_TOWER:
            raise ValueError("Tower must own LANDING_AREA before departure can start")
        flight_owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
        if flight_owner is None:
            self.core.claim_authority(
                session_id=session_id,
                scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
                agency=ControllerAgency.AIRPORT_TOWER,
                reason="Tower controls departure traffic until airborne handoff",
            )
        elif flight_owner.agency is not ControllerAgency.AIRPORT_TOWER:
            raise ValueError("Tower must own FLIGHT_TRAFFIC before departure can start")
        self.tower.start_departure(session_id=session_id, runway_id=runway_id)
        session = AirportDepartureSession(session_id=session_id, runway_id=runway_id)
        self._sessions[session_id] = session
        self._record(session, "departure procedure started at holding point")
        return session.model_copy(deep=True)

    def clear_line_up(self, session_id: UUID, *, reason: str) -> OperationalInstruction:
        session = self._require(session_id)
        if session.state is not AirportDepartureState.HOLDING_POINT:
            raise ValueError("Line-up clearance requires HOLDING_POINT state")
        instruction = self.tower.line_up_and_wait(session_id, reason=reason)
        session.state = AirportDepartureState.LINE_UP_CLEARED
        session.line_up_instruction_id = instruction.instruction_id
        self._sessions[session_id] = session
        self._record(session, reason)
        return instruction

    def confirm_lined_up(self, session_id: UUID) -> AirportDepartureSession:
        session = self._require(session_id)
        if session.state is not AirportDepartureState.LINE_UP_CLEARED:
            raise ValueError("Physical lineup requires LINE_UP_CLEARED state")
        self._require_acknowledged(session.line_up_instruction_id, "Line-up clearance")
        session.state = AirportDepartureState.LINED_UP
        self._sessions[session_id] = session
        self._record(session, "aircraft physically observed lined up on runway")
        return session.model_copy(deep=True)

    def clear_takeoff(self, session_id: UUID, *, reason: str) -> OperationalInstruction:
        session = self._require(session_id)
        if session.state not in {AirportDepartureState.HOLDING_POINT, AirportDepartureState.LINED_UP}:
            raise ValueError("Takeoff clearance is not valid from current departure state")
        instruction = self.tower.clear_takeoff(session_id, reason=reason)
        session.state = AirportDepartureState.TAKEOFF_CLEARED
        session.takeoff_instruction_id = instruction.instruction_id
        self._sessions[session_id] = session
        self._record(session, reason)
        return instruction

    def confirm_takeoff_roll(self, session_id: UUID) -> AirportDepartureSession:
        session = self._require(session_id)
        if session.state is not AirportDepartureState.TAKEOFF_CLEARED:
            raise ValueError("Takeoff roll requires TAKEOFF_CLEARED state")
        self._require_acknowledged(session.takeoff_instruction_id, "Takeoff clearance")
        self.tower.begin_takeoff_roll(session_id)
        session.state = AirportDepartureState.TAKEOFF_ROLL
        self._sessions[session_id] = session
        self._record(session, "takeoff roll physically observed")
        return session.model_copy(deep=True)

    def confirm_airborne(self, session_id: UUID) -> AirportDepartureSession:
        session = self._require(session_id)
        if session.state is not AirportDepartureState.TAKEOFF_ROLL:
            raise ValueError("AIRBORNE requires confirmed takeoff roll")
        self.tower.mark_airborne(session_id)
        session.state = AirportDepartureState.AIRBORNE
        self._sessions[session_id] = session
        self._record(session, "airborne event physically confirmed")
        return session.model_copy(deep=True)

    def begin_departure_handoff(self, session_id: UUID, *, reason: str) -> UUID:
        session = self._require(session_id)
        if session.state is not AirportDepartureState.AIRBORNE:
            raise ValueError("Tower to Departure handoff requires confirmed AIRBORNE state")
        handoff_id = self.core.acknowledgement_handoff(
            session_id=session_id,
            source=ControllerAgency.AIRPORT_TOWER,
            destination=ControllerAgency.AIRPORT_DEPARTURE,
            scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
            reason=reason,
        )
        session.departure_handoff_id = handoff_id
        self._sessions[session_id] = session
        return handoff_id

    def complete_departure_handoff(self, session_id: UUID) -> AirportDepartureSession:
        session = self._require(session_id)
        if session.state is not AirportDepartureState.AIRBORNE or session.departure_handoff_id is None:
            raise ValueError("Departure handoff is not ready to complete")
        self.core.complete_acknowledged_handoff(session.departure_handoff_id)
        session.state = AirportDepartureState.DEPARTURE_CONTROL
        self._sessions[session_id] = session
        self._record(session, "Departure accepted flight-traffic control")
        return session.model_copy(deep=True)

    def reject_takeoff(self, session_id: UUID, *, reason: str) -> AirportDepartureSession:
        session = self._require(session_id)
        if session.state is not AirportDepartureState.TAKEOFF_ROLL:
            raise ValueError("Rejected takeoff requires active takeoff roll")
        self.tower.reject_takeoff(session_id, reason=reason)
        session.state = AirportDepartureState.REJECTED_TAKEOFF
        self._sessions[session_id] = session
        self._record(session, reason)
        return session.model_copy(deep=True)

    def get(self, session_id: UUID) -> AirportDepartureSession | None:
        item = self._sessions.get(session_id)
        return item.model_copy(deep=True) if item else None

    def _require_acknowledged(self, instruction_id: UUID | None, label: str) -> None:
        if instruction_id is None:
            raise ValueError(f"{label} instruction is missing")
        instruction = self.core.instructions.get(instruction_id)
        if instruction is None or instruction.acknowledgement_state is not AcknowledgementState.ACKNOWLEDGED:
            raise ValueError(f"{label} must be acknowledged before physical commitment")

    def _require(self, session_id: UUID) -> AirportDepartureSession:
        item = self._sessions.get(session_id)
        if item is None:
            raise KeyError("Airport departure session not found")
        return item.model_copy(deep=True)

    def _record(self, session: AirportDepartureSession, reason: str) -> None:
        source = (
            ControllerAgency.AIRPORT_DEPARTURE
            if session.state is AirportDepartureState.DEPARTURE_CONTROL
            else ControllerAgency.AIRPORT_TOWER
        )
        self.core.history.record(
            session_id=session.session_id,
            event_type="airport_departure_state_changed",
            reason=reason,
            source_agency=source,
            details={"state": session.state.value, "runway_id": session.runway_id},
        )
