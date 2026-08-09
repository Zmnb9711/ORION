from __future__ import annotations

from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.airport_surface import RunwayState
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import CommitmentState, VoicePriority
from orion.atc_runtime import AtcCoreFlow


class RunwayOperationType(StrEnum):
    CROSSING = "crossing"
    LINE_UP = "line_up"
    TAKEOFF = "takeoff"
    LANDING = "landing"


class RunwayReservation(BaseModel):
    reservation_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    runway_id: str = Field(min_length=1, max_length=80)
    operation: RunwayOperationType
    commitment: CommitmentState = CommitmentState.RESERVED
    reason: str = Field(min_length=1, max_length=500)


class RunwayReservationManager:
    """Canonical protected-runway resource shared by crossing, line-up, takeoff and landing."""

    def __init__(self, core: AtcCoreFlow | None = None) -> None:
        self.core = core or AtcCoreFlow()
        self._lock = RLock()
        self._by_runway: dict[str, RunwayReservation] = {}

    def get(self, runway_id: str) -> RunwayReservation | None:
        with self._lock:
            item = self._by_runway.get(runway_id)
            return item.model_copy(deep=True) if item else None

    def reserve(self, reservation: RunwayReservation, runway_state: RunwayState) -> RunwayReservation:
        if not runway_state.usable_for_positive_clearance:
            raise ValueError("Runway state is not safe enough for positive reservation")
        with self._lock:
            current = self._by_runway.get(reservation.runway_id)
            if current is not None and current.session_id != reservation.session_id:
                raise ValueError(f"Runway {reservation.runway_id} already reserved for {current.operation.value}")
            if current is not None:
                raise ValueError("Runway operation is already reserved for this session")
            self._by_runway[reservation.runway_id] = reservation.model_copy(deep=True)
            self.core.history.record(
                session_id=reservation.session_id,
                event_type="runway_reserved",
                reason=reservation.reason,
                source_agency=ControllerAgency.AIRPORT_TOWER,
                related_id=reservation.reservation_id,
                details={
                    "runway_id": reservation.runway_id,
                    "operation": reservation.operation.value,
                    "commitment": reservation.commitment.name,
                },
            )
            return reservation.model_copy(deep=True)

    def change_operation(
        self,
        *,
        runway_id: str,
        session_id: UUID,
        operation: RunwayOperationType,
        reason: str,
    ) -> RunwayReservation:
        """Explicitly change an uncommitted reservation, e.g. LINE_UP -> TAKEOFF."""
        with self._lock:
            current = self._require(runway_id, session_id)
            if current.commitment >= CommitmentState.PHYSICALLY_COMMITTED:
                raise ValueError("Physically committed runway operation cannot change type")
            old_operation = current.operation
            current.operation = operation
            current.reason = reason
            self._by_runway[runway_id] = current.model_copy(deep=True)
            self.core.history.record(
                session_id=session_id,
                event_type="runway_operation_changed",
                reason=reason,
                source_agency=ControllerAgency.AIRPORT_TOWER,
                related_id=current.reservation_id,
                details={
                    "runway_id": runway_id,
                    "old_operation": old_operation.value,
                    "operation": operation.value,
                },
            )
            return current.model_copy(deep=True)

    def advance_commitment(
        self,
        *,
        runway_id: str,
        session_id: UUID,
        commitment: CommitmentState,
        reason: str,
    ) -> RunwayReservation:
        with self._lock:
            current = self._require(runway_id, session_id)
            if commitment < current.commitment:
                raise ValueError("Runway commitment cannot decrease implicitly")
            current.commitment = commitment
            self._by_runway[runway_id] = current.model_copy(deep=True)
            self.core.history.record(
                session_id=session_id,
                event_type="runway_commitment_changed",
                reason=reason,
                source_agency=ControllerAgency.AIRPORT_TOWER,
                related_id=current.reservation_id,
                details={"runway_id": runway_id, "commitment": commitment.name},
            )
            return current.model_copy(deep=True)

    def release(self, *, runway_id: str, session_id: UUID, reason: str) -> RunwayReservation:
        with self._lock:
            current = self._require(runway_id, session_id)
            if current.commitment >= CommitmentState.PHYSICALLY_COMMITTED:
                raise ValueError("Physically committed runway operation cannot be normally released")
            removed = self._by_runway.pop(runway_id)
            self.core.history.record(
                session_id=session_id,
                event_type="runway_reservation_released",
                reason=reason,
                source_agency=ControllerAgency.AIRPORT_TOWER,
                related_id=removed.reservation_id,
                details={"runway_id": runway_id, "operation": removed.operation.value},
            )
            return removed.model_copy(deep=True)

    def complete(self, *, runway_id: str, session_id: UUID, reason: str) -> RunwayReservation:
        with self._lock:
            removed = self._require(runway_id, session_id)
            self._by_runway.pop(runway_id)
            self.core.history.record(
                session_id=session_id,
                event_type="runway_operation_completed",
                reason=reason,
                source_agency=ControllerAgency.AIRPORT_TOWER,
                related_id=removed.reservation_id,
                details={"runway_id": runway_id, "operation": removed.operation.value},
            )
            return removed.model_copy(deep=True)

    def _require(self, runway_id: str, session_id: UUID) -> RunwayReservation:
        current = self._by_runway.get(runway_id)
        if current is None:
            raise KeyError("Runway reservation not found")
        if current.session_id != session_id:
            raise ValueError("Runway reservation belongs to another session")
        return current.model_copy(deep=True)


class AirportTowerBoundaryController:
    """Tower-side runway authority at the Ground/Tower boundary."""

    def __init__(self, reservations: RunwayReservationManager | None = None) -> None:
        self.reservations = reservations or RunwayReservationManager()
        self.core = self.reservations.core

    def assume_runway_authority(self, session_id: UUID, *, reason: str) -> None:
        self.core.claim_authority(
            session_id=session_id,
            scope=ControllerAuthorityScope.LANDING_AREA,
            agency=ControllerAgency.AIRPORT_TOWER,
            reason=reason,
        )

    def reserve_operation(
        self,
        *,
        session_id: UUID,
        runway_id: str,
        operation: RunwayOperationType,
        runway_state: RunwayState,
        reason: str,
    ) -> RunwayReservation:
        owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.LANDING_AREA)
        if owner is None or owner.agency is not ControllerAgency.AIRPORT_TOWER:
            raise ValueError("Tower does not own LANDING_AREA authority for this session")
        return self.reservations.reserve(
            RunwayReservation(
                session_id=session_id,
                runway_id=runway_id,
                operation=operation,
                reason=reason,
            ),
            runway_state,
        )

    def record_boundary_contact(self, session_id: UUID, *, runway_id: str, reason: str) -> None:
        ground = self.core.authority.get_owner(session_id, ControllerAuthorityScope.SURFACE_MOVEMENT)
        tower = self.core.authority.get_owner(session_id, ControllerAuthorityScope.LANDING_AREA)
        if ground is None or ground.agency is not ControllerAgency.AIRPORT_GROUND:
            raise ValueError("Ground SURFACE_MOVEMENT authority is not established")
        if tower is None or tower.agency is not ControllerAgency.AIRPORT_TOWER:
            raise ValueError("Tower LANDING_AREA authority is not established")
        self.core.history.record(
            session_id=session_id,
            event_type="ground_tower_boundary_contact",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            details={"runway_id": runway_id},
        )

    @staticmethod
    def conflict_voice_priority() -> VoicePriority:
        return VoicePriority.IMMEDIATE_SAFETY
