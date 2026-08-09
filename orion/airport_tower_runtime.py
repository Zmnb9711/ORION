from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.atc_core import ControllerAgency, ControllerAuthorityScope, HandoffTransferMode
from orion.atc_operations import OperationalInstruction, VoicePriority


class RunwayOperationKind(StrEnum):
    CROSSING = "crossing"
    LINE_UP = "line_up"
    TAKEOFF = "takeoff"
    LANDING = "landing"


class RunwayReservation(BaseModel):
    reservation_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    runway_id: str = Field(min_length=1, max_length=80)
    operation: RunwayOperationKind
    reason: str = Field(min_length=1, max_length=500)
    committed: bool = False


class AirportTowerController:
    """Tower-side runway authority and protected runway reservation facade."""

    def __init__(self, surface: AirportSurfaceCoordinator) -> None:
        self.surface = surface
        self.core = surface.core
        self._reservations: dict[UUID, RunwayReservation] = {}

    def assume_runway_control(self, session_id: UUID, *, reason: str) -> None:
        self.core.claim_authority(
            session_id=session_id,
            scope=ControllerAuthorityScope.LANDING_AREA,
            agency=ControllerAgency.AIRPORT_TOWER,
            reason=reason,
        )

    def begin_ground_boundary_handoff(self, session_id: UUID, *, reason: str) -> UUID:
        handoff = self.core.authority.begin_handoff(
            session_id=session_id,
            source_agency=ControllerAgency.AIRPORT_GROUND,
            destination_agency=ControllerAgency.AIRPORT_TOWER,
            scopes=[ControllerAuthorityScope.SURFACE_MOVEMENT],
            transfer_mode=HandoffTransferMode.ACKNOWLEDGEMENT_GATED,
            reason=reason,
        )
        self.core.history.record(
            session_id=session_id,
            event_type="ground_tower_boundary_handoff_started",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_GROUND,
            related_id=handoff.handoff_id,
        )
        return handoff.handoff_id

    def complete_ground_boundary_handoff(self, handoff_id: UUID) -> None:
        acknowledged = self.core.authority.acknowledge_handoff(handoff_id)
        completed = self.core.authority.complete_handoff(handoff_id)
        self.core.history.record(
            session_id=completed.session_id,
            event_type="ground_tower_boundary_handoff_completed",
            reason=completed.reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            related_id=completed.handoff_id,
            details={"source": acknowledged.source_agency.value},
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

    def issue_takeoff_clearance(self, reservation_id: UUID) -> OperationalInstruction:
        reservation = self._require_reservation(reservation_id)
        if reservation.operation is not RunwayOperationKind.TAKEOFF:
            raise ValueError("Reservation is not for takeoff")
        instruction = OperationalInstruction(
            session_id=reservation.session_id,
            issuing_agency=ControllerAgency.AIRPORT_TOWER,
            authority_scope=ControllerAuthorityScope.LANDING_AREA,
            semantic_action="takeoff_clearance",
            parameters={"runway_id": reservation.runway_id},
            acknowledgement_required=True,
            voice_priority=VoicePriority.PROCEDURAL,
        )
        return self.core.issue_instruction(instruction)

    def issue_landing_clearance(self, reservation_id: UUID) -> OperationalInstruction:
        reservation = self._require_reservation(reservation_id)
        if reservation.operation is not RunwayOperationKind.LANDING:
            raise ValueError("Reservation is not for landing")
        instruction = OperationalInstruction(
            session_id=reservation.session_id,
            issuing_agency=ControllerAgency.AIRPORT_TOWER,
            authority_scope=ControllerAuthorityScope.LANDING_AREA,
            semantic_action="landing_clearance",
            parameters={"runway_id": reservation.runway_id},
            acknowledgement_required=True,
            voice_priority=VoicePriority.PROCEDURAL,
        )
        return self.core.issue_instruction(instruction)

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
        self.surface.release_protected_runway(
            session_id=reservation.session_id,
            runway_id=reservation.runway_id,
        )
        self._reservations.pop(reservation_id, None)

    def complete_reservation(self, reservation_id: UUID) -> None:
        reservation = self._require_reservation(reservation_id)
        self.surface.release_protected_runway(
            session_id=reservation.session_id,
            runway_id=reservation.runway_id,
        )
        self._reservations.pop(reservation_id, None)
        self.core.history.record(
            session_id=reservation.session_id,
            event_type="runway_operation_completed",
            reason=reservation.reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            related_id=reservation.reservation_id,
            details={"runway_id": reservation.runway_id, "operation": reservation.operation.value},
        )

    def _require_reservation(self, reservation_id: UUID) -> RunwayReservation:
        item = self._reservations.get(reservation_id)
        if item is None:
            raise KeyError("Runway reservation not found")
        return item.model_copy(deep=True)
