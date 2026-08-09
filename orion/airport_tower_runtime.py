from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import OperationalInstruction, VoicePriority


class RunwayOperationKind(StrEnum):
    CROSSING = "crossing"
    LINE_UP = "line_up"
    TAKEOFF = "takeoff"
    LANDING = "landing"


class TowerDepartureState(StrEnum):
    HOLD_SHORT = "hold_short"
    LINE_UP_AND_WAIT = "line_up_and_wait"
    TAKEOFF_CLEARED = "takeoff_cleared"
    TAKEOFF_ROLL = "takeoff_roll"
    AIRBORNE = "airborne"
    REJECTED_TAKEOFF = "rejected_takeoff"


class TowerArrivalState(StrEnum):
    FINAL = "final"
    LANDING_CLEARED = "landing_cleared"
    LANDING_ATTEMPT = "landing_attempt"
    ROLLOUT = "rollout"
    RUNWAY_VACATED = "runway_vacated"
    GO_AROUND = "go_around"


class RunwayReservation(BaseModel):
    reservation_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    runway_id: str = Field(min_length=1, max_length=80)
    operation: RunwayOperationKind
    reason: str = Field(min_length=1, max_length=500)
    committed: bool = False


class TowerDepartureSession(BaseModel):
    session_id: UUID
    runway_id: str
    state: TowerDepartureState = TowerDepartureState.HOLD_SHORT
    reservation_id: UUID | None = None


class TowerArrivalSession(BaseModel):
    session_id: UUID
    runway_id: str
    state: TowerArrivalState = TowerArrivalState.FINAL
    reservation_id: UUID | None = None


class AirportTowerController:
    """Tower-side runway authority and procedural runway state machines."""

    def __init__(self, surface: AirportSurfaceCoordinator) -> None:
        self.surface = surface
        self.core = surface.core
        self._reservations: dict[UUID, RunwayReservation] = {}
        self._departures: dict[UUID, TowerDepartureSession] = {}
        self._arrivals: dict[UUID, TowerArrivalSession] = {}

    def assume_runway_control(self, session_id: UUID, *, reason: str) -> None:
        self.core.claim_authority(
            session_id=session_id,
            scope=ControllerAuthorityScope.LANDING_AREA,
            agency=ControllerAgency.AIRPORT_TOWER,
            reason=reason,
        )

    def record_ground_boundary_contact(self, session_id: UUID, *, reason: str) -> None:
        """Record the Ground/Tower procedural boundary without transferring SURFACE_MOVEMENT."""
        ground_owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.SURFACE_MOVEMENT)
        tower_owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.LANDING_AREA)
        if ground_owner is None or ground_owner.agency is not ControllerAgency.AIRPORT_GROUND:
            raise ValueError("Ground does not own surface movement for this session")
        if tower_owner is None or tower_owner.agency is not ControllerAgency.AIRPORT_TOWER:
            raise ValueError("Tower does not own landing-area authority for this session")
        self.core.history.record(
            session_id=session_id,
            event_type="ground_tower_boundary_contact",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
        )

    def reserve_runway(
        self,
        *,
        session_id: UUID,
        runway_id: str,
        operation: RunwayOperationKind,
        reason: str,
    ) -> RunwayReservation:
        self.surface.reserve_protected_runway(session_id=session_id, runway_id=runway_id, reason=reason)
        reservation = RunwayReservation(
            session_id=session_id,
            runway_id=runway_id,
            operation=operation,
            reason=reason,
        )
        self._reservations[reservation.reservation_id] = reservation
        self.core.history.record(
            session_id=session_id,
            event_type="runway_operation_reserved",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            related_id=reservation.reservation_id,
            details={"runway_id": runway_id, "operation": operation.value},
        )
        return reservation.model_copy(deep=True)

    def start_departure(self, *, session_id: UUID, runway_id: str) -> TowerDepartureSession:
        session = TowerDepartureSession(session_id=session_id, runway_id=runway_id)
        self._departures[session_id] = session
        self.core.history.record(
            session_id=session_id,
            event_type="tower_departure_started",
            reason="aircraft holding short for departure",
            source_agency=ControllerAgency.AIRPORT_TOWER,
            details={"runway_id": runway_id},
        )
        return session.model_copy(deep=True)

    def line_up_and_wait(self, session_id: UUID, *, reason: str) -> OperationalInstruction:
        session = self._require_departure(session_id)
        if session.state is not TowerDepartureState.HOLD_SHORT:
            raise ValueError("Line-up is only valid from hold-short")
        reservation = self.reserve_runway(
            session_id=session_id,
            runway_id=session.runway_id,
            operation=RunwayOperationKind.LINE_UP,
            reason=reason,
        )
        session.state = TowerDepartureState.LINE_UP_AND_WAIT
        session.reservation_id = reservation.reservation_id
        self._departures[session_id] = session
        return self._issue_runway_instruction(
            session_id=session_id,
            semantic_action="line_up_and_wait",
            runway_id=session.runway_id,
        )

    def clear_takeoff(self, session_id: UUID, *, reason: str) -> OperationalInstruction:
        session = self._require_departure(session_id)
        if session.state not in {TowerDepartureState.HOLD_SHORT, TowerDepartureState.LINE_UP_AND_WAIT}:
            raise ValueError("Takeoff clearance is not valid from current departure state")
        if session.reservation_id is None:
            reservation = self.reserve_runway(
                session_id=session_id,
                runway_id=session.runway_id,
                operation=RunwayOperationKind.TAKEOFF,
                reason=reason,
            )
            session.reservation_id = reservation.reservation_id
        else:
            reservation = self._require_reservation(session.reservation_id)
            reservation.operation = RunwayOperationKind.TAKEOFF
            reservation.reason = reason
            self._reservations[reservation.reservation_id] = reservation
        session.state = TowerDepartureState.TAKEOFF_CLEARED
        self._departures[session_id] = session
        return self._issue_runway_instruction(
            session_id=session_id,
            semantic_action="takeoff_clearance",
            runway_id=session.runway_id,
        )

    def begin_takeoff_roll(self, session_id: UUID) -> TowerDepartureSession:
        session = self._require_departure(session_id)
        if session.state is not TowerDepartureState.TAKEOFF_CLEARED:
            raise ValueError("Takeoff roll requires takeoff clearance")
        self.commit_reservation(self._require_reservation_id(session.reservation_id))
        session.state = TowerDepartureState.TAKEOFF_ROLL
        self._departures[session_id] = session
        self._record_departure_state(session, "takeoff roll observed")
        return session.model_copy(deep=True)

    def mark_airborne(self, session_id: UUID) -> TowerDepartureSession:
        session = self._require_departure(session_id)
        if session.state is not TowerDepartureState.TAKEOFF_ROLL:
            raise ValueError("Airborne event requires takeoff roll")
        session.state = TowerDepartureState.AIRBORNE
        self._departures[session_id] = session
        self.complete_reservation(self._require_reservation_id(session.reservation_id))
        session.reservation_id = None
        self._departures[session_id] = session
        self._record_departure_state(session, "airborne event confirmed")
        return session.model_copy(deep=True)

    def reject_takeoff(self, session_id: UUID, *, reason: str) -> TowerDepartureSession:
        session = self._require_departure(session_id)
        if session.state is not TowerDepartureState.TAKEOFF_ROLL:
            raise ValueError("Rejected takeoff requires active takeoff roll")
        session.state = TowerDepartureState.REJECTED_TAKEOFF
        self._departures[session_id] = session
        self._record_departure_state(session, reason)
        return session.model_copy(deep=True)

    def start_arrival(self, *, session_id: UUID, runway_id: str) -> TowerArrivalSession:
        session = TowerArrivalSession(session_id=session_id, runway_id=runway_id)
        self._arrivals[session_id] = session
        self.core.history.record(
            session_id=session_id,
            event_type="tower_arrival_started",
            reason="arrival on final under Tower runway control",
            source_agency=ControllerAgency.AIRPORT_TOWER,
            details={"runway_id": runway_id},
        )
        return session.model_copy(deep=True)

    def clear_landing(self, session_id: UUID, *, reason: str) -> OperationalInstruction:
        session = self._require_arrival(session_id)
        if session.state is not TowerArrivalState.FINAL:
            raise ValueError("Landing clearance is only valid from final")
        reservation = self.reserve_runway(
            session_id=session_id,
            runway_id=session.runway_id,
            operation=RunwayOperationKind.LANDING,
            reason=reason,
        )
        session.state = TowerArrivalState.LANDING_CLEARED
        session.reservation_id = reservation.reservation_id
        self._arrivals[session_id] = session
        return self._issue_runway_instruction(
            session_id=session_id,
            semantic_action="landing_clearance",
            runway_id=session.runway_id,
        )

    def begin_landing_attempt(self, session_id: UUID) -> TowerArrivalSession:
        session = self._require_arrival(session_id)
        if session.state is not TowerArrivalState.LANDING_CLEARED:
            raise ValueError("Landing attempt requires landing clearance")
        self.commit_reservation(self._require_reservation_id(session.reservation_id))
        session.state = TowerArrivalState.LANDING_ATTEMPT
        self._arrivals[session_id] = session
        self._record_arrival_state(session, "landing attempt committed")
        return session.model_copy(deep=True)

    def mark_rollout(self, session_id: UUID) -> TowerArrivalSession:
        session = self._require_arrival(session_id)
        if session.state is not TowerArrivalState.LANDING_ATTEMPT:
            raise ValueError("Rollout requires landing attempt")
        session.state = TowerArrivalState.ROLLOUT
        self._arrivals[session_id] = session
        self._record_arrival_state(session, "touchdown and rollout observed")
        return session.model_copy(deep=True)

    def mark_runway_vacated(self, session_id: UUID) -> TowerArrivalSession:
        session = self._require_arrival(session_id)
        if session.state is not TowerArrivalState.ROLLOUT:
            raise ValueError("Runway-vacated event requires rollout")
        session.state = TowerArrivalState.RUNWAY_VACATED
        self._arrivals[session_id] = session
        self.complete_reservation(self._require_reservation_id(session.reservation_id))
        session.reservation_id = None
        self._arrivals[session_id] = session
        self._record_arrival_state(session, "runway-vacated event confirmed")
        return session.model_copy(deep=True)

    def go_around(self, session_id: UUID, *, reason: str) -> TowerArrivalSession:
        session = self._require_arrival(session_id)
        if session.state not in {TowerArrivalState.FINAL, TowerArrivalState.LANDING_CLEARED}:
            raise ValueError("Go-around is not valid from current arrival state")
        if session.reservation_id is not None:
            reservation = self._require_reservation(session.reservation_id)
            if not reservation.committed:
                self.release_reservation(reservation.reservation_id)
            session.reservation_id = None
        session.state = TowerArrivalState.GO_AROUND
        self._arrivals[session_id] = session
        self._record_arrival_state(session, reason)
        return session.model_copy(deep=True)

    def commit_reservation(self, reservation_id: UUID) -> RunwayReservation:
        reservation = self._require_reservation(reservation_id)
        reservation.committed = True
        self._reservations[reservation_id] = reservation
        self.core.history.record(
            session_id=reservation.session_id,
            event_type="runway_operation_committed",
            reason=reservation.reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            related_id=reservation.reservation_id,
            details={"runway_id": reservation.runway_id, "operation": reservation.operation.value},
        )
        return reservation.model_copy(deep=True)

    def release_reservation(self, reservation_id: UUID) -> None:
        reservation = self._require_reservation(reservation_id)
        if reservation.committed:
            raise ValueError("Committed runway operation cannot be normally released")
        self.surface.release_protected_runway(session_id=reservation.session_id, runway_id=reservation.runway_id)
        self._reservations.pop(reservation_id, None)

    def complete_reservation(self, reservation_id: UUID) -> None:
        reservation = self._require_reservation(reservation_id)
        self.surface.release_protected_runway(session_id=reservation.session_id, runway_id=reservation.runway_id)
        self._reservations.pop(reservation_id, None)
        self.core.history.record(
            session_id=reservation.session_id,
            event_type="runway_operation_completed",
            reason=reservation.reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            related_id=reservation.reservation_id,
            details={"runway_id": reservation.runway_id, "operation": reservation.operation.value},
        )

    def _issue_runway_instruction(self, *, session_id: UUID, semantic_action: str, runway_id: str) -> OperationalInstruction:
        return self.core.issue_instruction(
            OperationalInstruction(
                session_id=session_id,
                issuing_agency=ControllerAgency.AIRPORT_TOWER,
                authority_scope=ControllerAuthorityScope.LANDING_AREA,
                semantic_action=semantic_action,
                parameters={"runway_id": runway_id},
                acknowledgement_required=True,
                voice_priority=VoicePriority.PROCEDURAL,
            )
        )

    def _record_departure_state(self, session: TowerDepartureSession, reason: str) -> None:
        self.core.history.record(
            session_id=session.session_id,
            event_type="tower_departure_state_changed",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            details={"state": session.state.value, "runway_id": session.runway_id},
        )

    def _record_arrival_state(self, session: TowerArrivalSession, reason: str) -> None:
        self.core.history.record(
            session_id=session.session_id,
            event_type="tower_arrival_state_changed",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            details={"state": session.state.value, "runway_id": session.runway_id},
        )

    def _require_departure(self, session_id: UUID) -> TowerDepartureSession:
        item = self._departures.get(session_id)
        if item is None:
            raise KeyError("Tower departure session not found")
        return item.model_copy(deep=True)

    def _require_arrival(self, session_id: UUID) -> TowerArrivalSession:
        item = self._arrivals.get(session_id)
        if item is None:
            raise KeyError("Tower arrival session not found")
        return item.model_copy(deep=True)

    def _require_reservation(self, reservation_id: UUID) -> RunwayReservation:
        item = self._reservations.get(reservation_id)
        if item is None:
            raise KeyError("Runway reservation not found")
        return item.model_copy(deep=True)

    @staticmethod
    def _require_reservation_id(reservation_id: UUID | None) -> UUID:
        if reservation_id is None:
            raise ValueError("Runway reservation is missing")
        return reservation_id
