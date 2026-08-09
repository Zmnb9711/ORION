from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.atc_core import (
    AtcAuthorityRegistry,
    AtcSessionIdentity,
    ControllerAgency,
    ControllerAuthorityScope,
    HandoffTransferMode,
)
from orion.atc_operations import (
    CommitmentState,
    InstructionState,
    OperationalInstruction,
    ResourceAssignment,
    TrafficConflict,
    TrafficPriority,
)


class AtcEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    event_type: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)
    source_agency: ControllerAgency | None = None
    related_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)


class AtcEventHistory:
    def __init__(self) -> None:
        self._lock = RLock()
        self._events: dict[UUID, list[AtcEvent]] = {}

    def append(self, event: AtcEvent) -> AtcEvent:
        with self._lock:
            self._events.setdefault(event.session_id, []).append(event.model_copy(deep=True))
            return event.model_copy(deep=True)

    def record(
        self,
        *,
        session_id: UUID,
        event_type: str,
        reason: str,
        source_agency: ControllerAgency | None = None,
        related_id: UUID | None = None,
        details: dict[str, str | int | float | bool] | None = None,
    ) -> AtcEvent:
        return self.append(
            AtcEvent(
                session_id=session_id,
                event_type=event_type,
                reason=reason,
                source_agency=source_agency,
                related_id=related_id,
                details=details or {},
            )
        )

    def list(self, session_id: UUID) -> list[AtcEvent]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._events.get(session_id, [])]

    def clear(self, session_id: UUID) -> None:
        with self._lock:
            self._events.pop(session_id, None)


class AtcInstructionRegistry:
    def __init__(self, history: AtcEventHistory | None = None) -> None:
        self._lock = RLock()
        self._instructions: dict[UUID, OperationalInstruction] = {}
        self._history = history or AtcEventHistory()

    def create(self, instruction: OperationalInstruction) -> OperationalInstruction:
        with self._lock:
            if instruction.instruction_id in self._instructions:
                raise ValueError("ATC instruction already exists")
            self._instructions[instruction.instruction_id] = instruction.model_copy(deep=True)
            self._history.record(
                session_id=instruction.session_id,
                event_type="instruction_created",
                reason=instruction.semantic_action,
                source_agency=instruction.issuing_agency,
                related_id=instruction.instruction_id,
            )
            return instruction.model_copy(deep=True)

    def get(self, instruction_id: UUID) -> OperationalInstruction | None:
        with self._lock:
            item = self._instructions.get(instruction_id)
            return item.model_copy(deep=True) if item else None

    def list_session(self, session_id: UUID) -> list[OperationalInstruction]:
        with self._lock:
            items = [item for item in self._instructions.values() if item.session_id == session_id]
            return [item.model_copy(deep=True) for item in sorted(items, key=lambda item: item.issued_at)]

    def transmit(self, instruction_id: UUID) -> OperationalInstruction:
        with self._lock:
            item = self._require(instruction_id)
            item.mark_transmitted()
            self._history.record(
                session_id=item.session_id,
                event_type="instruction_transmitted",
                reason=item.semantic_action,
                source_agency=item.issuing_agency,
                related_id=item.instruction_id,
            )
            return item.model_copy(deep=True)

    def acknowledge(self, instruction_id: UUID) -> OperationalInstruction:
        with self._lock:
            item = self._require(instruction_id)
            item.acknowledge()
            self._history.record(
                session_id=item.session_id,
                event_type="instruction_acknowledged",
                reason=item.semantic_action,
                source_agency=item.issuing_agency,
                related_id=item.instruction_id,
            )
            return item.model_copy(deep=True)

    def reject(self, instruction_id: UUID) -> OperationalInstruction:
        with self._lock:
            item = self._require(instruction_id)
            item.reject()
            self._history.record(
                session_id=item.session_id,
                event_type="instruction_rejected",
                reason=item.semantic_action,
                source_agency=item.issuing_agency,
                related_id=item.instruction_id,
            )
            return item.model_copy(deep=True)

    def retry(self, instruction_id: UUID) -> OperationalInstruction:
        with self._lock:
            item = self._require(instruction_id)
            item.retry()
            self._history.record(
                session_id=item.session_id,
                event_type="instruction_retry_scheduled",
                reason=item.semantic_action,
                source_agency=item.issuing_agency,
                related_id=item.instruction_id,
                details={"retry_count": item.retry_count},
            )
            return item.model_copy(deep=True)

    def expire_due(self, now: datetime | None = None) -> list[OperationalInstruction]:
        current = now or datetime.now(UTC)
        expired: list[OperationalInstruction] = []
        with self._lock:
            for item in self._instructions.values():
                if item.expire_if_due(current):
                    self._history.record(
                        session_id=item.session_id,
                        event_type="instruction_expired",
                        reason=item.semantic_action,
                        source_agency=item.issuing_agency,
                        related_id=item.instruction_id,
                    )
                    expired.append(item.model_copy(deep=True))
        return expired

    def clear_session(self, session_id: UUID) -> None:
        with self._lock:
            for instruction_id in [
                item.instruction_id for item in self._instructions.values() if item.session_id == session_id
            ]:
                self._instructions.pop(instruction_id, None)

    def _require(self, instruction_id: UUID) -> OperationalInstruction:
        item = self._instructions.get(instruction_id)
        if item is None:
            raise KeyError("ATC instruction not found")
        return item


class AtcCoordinationRegistry:
    """Domain-neutral conflict and exclusive resource-assignment registry."""

    def __init__(self, history: AtcEventHistory | None = None) -> None:
        self._lock = RLock()
        self._assignments: dict[tuple[str, str], ResourceAssignment] = {}
        self._conflicts: dict[UUID, TrafficConflict] = {}
        self._history = history or AtcEventHistory()

    def assign_resource(self, assignment: ResourceAssignment) -> ResourceAssignment:
        key = (assignment.resource_type, assignment.resource_id)
        with self._lock:
            current = self._assignments.get(key)
            if current is not None and current.session_id != assignment.session_id:
                raise ValueError(
                    f"Resource {assignment.resource_type}:{assignment.resource_id} is already assigned"
                )
            self._assignments[key] = assignment.model_copy(deep=True)
            self._history.record(
                session_id=assignment.session_id,
                event_type="resource_assigned",
                reason=assignment.reason,
                related_id=assignment.assignment_id,
                details={
                    "resource_type": assignment.resource_type,
                    "resource_id": assignment.resource_id,
                    "revision": assignment.revision,
                },
            )
            return assignment.model_copy(deep=True)

    def release_resource(self, *, resource_type: str, resource_id: str, session_id: UUID) -> None:
        key = (resource_type, resource_id)
        with self._lock:
            current = self._assignments.get(key)
            if current is None:
                return
            if current.session_id != session_id:
                raise ValueError("Resource assignment belongs to another session")
            self._assignments.pop(key)
            self._history.record(
                session_id=session_id,
                event_type="resource_released",
                reason="resource released",
                related_id=current.assignment_id,
                details={"resource_type": resource_type, "resource_id": resource_id},
            )

    def record_conflict(self, conflict: TrafficConflict) -> TrafficConflict:
        with self._lock:
            self._conflicts[conflict.conflict_id] = conflict.model_copy(deep=True)
            for session_id in conflict.sessions:
                self._history.record(
                    session_id=session_id,
                    event_type="traffic_conflict_detected",
                    reason=conflict.reason,
                    related_id=conflict.conflict_id,
                    details={"class_name": conflict.class_name},
                )
            return conflict.model_copy(deep=True)

    def list_conflicts(self, session_id: UUID) -> list[TrafficConflict]:
        with self._lock:
            items = [item for item in self._conflicts.values() if session_id in item.sessions]
            return [item.model_copy(deep=True) for item in sorted(items, key=lambda item: item.detected_at)]


class AtcCoreFlow:
    """Small orchestration facade proving the generic ATC primitives compose end-to-end."""

    def __init__(self) -> None:
        self.history = AtcEventHistory()
        self.authority = AtcAuthorityRegistry()
        self.instructions = AtcInstructionRegistry(self.history)
        self.coordination = AtcCoordinationRegistry(self.history)

    def open_session(self, identity: AtcSessionIdentity) -> AtcSessionIdentity:
        self.history.record(
            session_id=identity.session_id,
            event_type="session_opened",
            reason="ATC session opened",
            details={
                "mission_id": identity.mission_id,
                "aircraft_id": identity.aircraft_id,
                "facility_id": identity.facility_id or "",
            },
        )
        return identity.model_copy(deep=True)

    def claim_authority(
        self,
        *,
        session_id: UUID,
        scope: ControllerAuthorityScope,
        agency: ControllerAgency,
        reason: str,
    ) -> None:
        ownership = self.authority.claim(
            session_id=session_id,
            scope=scope,
            agency=agency,
            reason=reason,
        )
        self.history.record(
            session_id=session_id,
            event_type="authority_claimed",
            reason=reason,
            source_agency=agency,
            details={"scope": ownership.scope.value},
        )

    def issue_instruction(self, instruction: OperationalInstruction) -> OperationalInstruction:
        owner = self.authority.get_owner(instruction.session_id, instruction.authority_scope)
        if owner is None or owner.agency is not instruction.issuing_agency:
            raise ValueError("Issuing agency does not own the required authority scope")
        return self.instructions.create(instruction)

    def acknowledgement_handoff(
        self,
        *,
        session_id: UUID,
        source: ControllerAgency,
        destination: ControllerAgency,
        scope: ControllerAuthorityScope,
        reason: str,
    ) -> UUID:
        handoff = self.authority.begin_handoff(
            session_id=session_id,
            source_agency=source,
            destination_agency=destination,
            scopes=[scope],
            transfer_mode=HandoffTransferMode.ACKNOWLEDGEMENT_GATED,
            reason=reason,
        )
        self.history.record(
            session_id=session_id,
            event_type="handoff_started",
            reason=reason,
            source_agency=source,
            related_id=handoff.handoff_id,
            details={"destination": destination.value, "scope": scope.value},
        )
        return handoff.handoff_id

    def complete_acknowledged_handoff(self, handoff_id: UUID) -> None:
        acknowledged = self.authority.acknowledge_handoff(handoff_id)
        completed = self.authority.complete_handoff(handoff_id)
        self.history.record(
            session_id=completed.session_id,
            event_type="handoff_completed",
            reason=completed.reason,
            source_agency=completed.destination_agency,
            related_id=completed.handoff_id,
            details={
                "source": acknowledged.source_agency.value,
                "destination": completed.destination_agency.value,
            },
        )

    @staticmethod
    def should_protect(entry_priority: TrafficPriority, commitment: CommitmentState) -> bool:
        return (
            entry_priority >= TrafficPriority.CRITICAL_FUEL
            or commitment >= CommitmentState.PHYSICALLY_COMMITTED
        )


atc_event_history = AtcEventHistory()
atc_instruction_registry = AtcInstructionRegistry(atc_event_history)
atc_coordination_registry = AtcCoordinationRegistry(atc_event_history)
