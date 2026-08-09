from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from orion.airport_runway_coordination import (
    RunwayOperationType,
    RunwayReservation,
)
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import CommitmentState, OperationalInstruction, VoicePriority


RunwayOperationKind = RunwayOperationType


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
        self.reservations = surface.reservations
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
        owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.LANDING_AREA)
        if owner is None or owner.agency is not ControllerAgency.AIRPORT_TOWER:
            raise ValueError("Tower does not own LANDING_AREA authority for this session")
        runway = self.surface.runways.require_positive_clearance_state(runway_id)
        return self.reservations.reserve(
            RunwayReservation(
                session_id=session_id,
                runway_id=runway_id,
                operation=operation,
                reason=reason,
            ),
            runway,
        )

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
            reservation = self.reservations.change_operation(
                runway_id=session.runway_id,
                session_id=session_id,
                operation=RunwayOperationKind.TAKEOFF,
                reason=reason,
            )
            session.reservation_id = reservation.reservation_id
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
        self.reservations.advance_commitment(
            runway_id=session.runway_id,
            session_id=session_id,
            commitment=CommitmentState.PHYSICALLY_COMMITTED,
            reason="takeoff roll observed",
        )
        session.state = TowerDepartureState.TAKEOFF_ROLL
        self._departures[session_id] = session
        self._record_departure_state(session, "takeoff roll observed")
        return session.model_copy(deep=True)

    def mark_airborne(self, session_id: UUID) -> TowerDepartureSession:
        session = self._require_departure(session_id)
        if session.state is not TowerDepartureState.TAKEOFF_ROLL:
            raise ValueError("Airborne event requires takeoff roll")
        self.reservations.complete(
            runway_id=session.runway_id,
            session_id=session_id,
            reason="airborne event confirmed",
        )
        session.state = TowerDepartureState.AIRBORNE
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
        self.reservations.advance_commitment(
            runway_id=session.runway_id,
            session_id=session_id,
            commitment=CommitmentState.PHYSICALLY_COMMITTED,
            reason="landing attempt committed",
        )
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
        self.reservations.complete(
            runway_id=session.runway_id,
            session_id=session_id,
            reason="runway-vacated event confirmed",
        )
        session.state = TowerArrivalState.RUNWAY_VACATED
        session.reservation_id = None
        self._arrivals[session_id] = session
        self._record_arrival_state(session, "runway-vacated event confirmed")
        return session.model_copy(deep=True)

    def go_around(self, session_id: UUID, *, reason: str) -> TowerArrivalSession:
        session = self._require_arrival(session_id)
        if session.state not in {TowerArrivalState.FINAL, TowerArrivalState.LANDING_CLEARED}:
            raise ValueError("Go-around is not valid from current arrival state")
        if session.reservation_id is not None:
            reservation = self.reservations.get(session.runway_id)
            if reservation is not None and reservation.commitment < CommitmentState.PHYSICALLY_COMMITTED:
                self.reservations.release(
                    runway_id=session.runway_id,
                    session_id=session_id,
                    reason=reason,
                )
            session.reservation_id = None
        session.state = TowerArrivalState.GO_AROUND
        self._arrivals[session_id] = session
        self._record_arrival_state(session, reason)
        return session.model_copy(deep=True)

    def _issue_runway_instruction(
        self,
        *,
        session_id: UUID,
        semantic_action: str,
        runway_id: str,
    ) -> OperationalInstruction:
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
