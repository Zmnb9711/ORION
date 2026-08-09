from __future__ import annotations

from uuid import UUID

from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import (
    CommitmentState,
    OperationalInstruction,
    OperationalOverlay,
    SequencedTrafficEntry,
    TrafficConflict,
    TrafficPriority,
)
from orion.atc_runtime import AtcCoreFlow
from orion.atc_session_state import (
    AtcRuntimeSession,
    AtcSessionRuntimeStore,
    GenericConflictResolutionPolicy,
    GenericSequencingPolicy,
)


class AtcIntegratedRuntime:
    """Single facade that keeps ATC runtime state and audit history consistent."""

    def __init__(self) -> None:
        self.core = AtcCoreFlow()
        self.sessions = AtcSessionRuntimeStore()
        self.sequencing = GenericSequencingPolicy()
        self.conflicts = GenericConflictResolutionPolicy()

    def open_session(self, identity: AtcSessionIdentity, *, procedural_state: str) -> AtcRuntimeSession:
        runtime = AtcRuntimeSession(identity=identity, procedural_state=procedural_state)
        created = self.sessions.create(runtime)
        self.core.open_session(identity)
        self.core.history.record(
            session_id=identity.session_id,
            event_type="procedural_state_initialized",
            reason="initial ATC procedural state",
            details={"procedural_state": procedural_state, "revision": created.revision},
        )
        return created

    def transition(self, session_id: UUID, procedural_state: str, *, reason: str) -> AtcRuntimeSession:
        runtime = self._require_session(session_id)
        previous = runtime.procedural_state
        runtime.transition(procedural_state, reason=reason)
        stored = self.sessions.replace(runtime)
        self.core.history.record(
            session_id=session_id,
            event_type="procedural_state_changed",
            reason=reason,
            details={
                "previous_state": previous,
                "procedural_state": procedural_state,
                "revision": stored.revision,
            },
        )
        return stored

    def add_overlay(self, session_id: UUID, overlay: OperationalOverlay, *, reason: str) -> AtcRuntimeSession:
        runtime = self._require_session(session_id)
        runtime.add_overlay(overlay, reason=reason)
        stored = self.sessions.replace(runtime)
        self.core.history.record(
            session_id=session_id,
            event_type="operational_overlay_added",
            reason=reason,
            details={"overlay": overlay.value, "procedural_state": stored.procedural_state},
        )
        return stored

    def remove_overlay(self, session_id: UUID, overlay: OperationalOverlay, *, reason: str) -> AtcRuntimeSession:
        runtime = self._require_session(session_id)
        runtime.remove_overlay(overlay, reason=reason)
        stored = self.sessions.replace(runtime)
        self.core.history.record(
            session_id=session_id,
            event_type="operational_overlay_removed",
            reason=reason,
            details={"overlay": overlay.value, "procedural_state": stored.procedural_state},
        )
        return stored

    def set_priority(self, session_id: UUID, priority: TrafficPriority, *, reason: str) -> AtcRuntimeSession:
        runtime = self._require_session(session_id)
        previous = runtime.priority
        runtime.set_priority(priority, reason=reason)
        stored = self.sessions.replace(runtime)
        self.core.history.record(
            session_id=session_id,
            event_type="traffic_priority_changed",
            reason=reason,
            details={"previous": int(previous), "current": int(priority)},
        )
        return stored

    def set_commitment(
        self,
        session_id: UUID,
        commitment: CommitmentState,
        *,
        reason: str,
    ) -> AtcRuntimeSession:
        runtime = self._require_session(session_id)
        previous = runtime.commitment
        runtime.set_commitment(commitment, reason=reason)
        stored = self.sessions.replace(runtime)
        self.core.history.record(
            session_id=session_id,
            event_type="commitment_changed",
            reason=reason,
            details={"previous": int(previous), "current": int(commitment)},
        )
        return stored

    def claim_authority(
        self,
        *,
        session_id: UUID,
        scope: ControllerAuthorityScope,
        agency: ControllerAgency,
        reason: str,
    ) -> None:
        self._require_session(session_id)
        self.core.claim_authority(session_id=session_id, scope=scope, agency=agency, reason=reason)

    def issue_instruction(self, instruction: OperationalInstruction) -> OperationalInstruction:
        self._require_session(instruction.session_id)
        created = self.core.issue_instruction(instruction)
        return self.core.instructions.transmit(created.instruction_id)

    def acknowledge_instruction(self, instruction_id: UUID) -> OperationalInstruction:
        return self.core.instructions.acknowledge(instruction_id)

    def sequence(self, session_ids: list[UUID]) -> list[SequencedTrafficEntry]:
        entries: list[SequencedTrafficEntry] = []
        for index, session_id in enumerate(session_ids):
            runtime = self._require_session(session_id)
            entries.append(
                SequencedTrafficEntry(
                    session_id=session_id,
                    priority=runtime.priority,
                    commitment=runtime.commitment,
                    sequence_index=index,
                    reason=runtime.last_reason,
                    revision=runtime.revision,
                )
            )
        ordered = self.sequencing.order(entries)
        for position, entry in enumerate(ordered):
            self.core.history.record(
                session_id=entry.session_id,
                event_type="traffic_sequence_evaluated",
                reason="generic sequencing policy",
                details={
                    "position": position,
                    "priority": int(entry.priority),
                    "commitment": int(entry.commitment),
                },
            )
        return ordered

    def resolve_conflict(self, conflict: TrafficConflict) -> tuple[str, str]:
        self.core.coordination.record_conflict(conflict)
        entries = {
            session_id: SequencedTrafficEntry(
                session_id=session_id,
                priority=runtime.priority,
                commitment=runtime.commitment,
                sequence_index=index,
                reason=runtime.last_reason,
                revision=runtime.revision,
            )
            for index, session_id in enumerate(conflict.sessions)
            if (runtime := self.sessions.get(session_id)) is not None
        }
        action, reason = self.conflicts.resolve(conflict, entries)
        for session_id in conflict.sessions:
            if self.sessions.get(session_id) is not None:
                self.core.history.record(
                    session_id=session_id,
                    event_type="traffic_conflict_resolved",
                    reason=reason,
                    related_id=conflict.conflict_id,
                    details={"action": action},
                )
        return action, reason

    def _require_session(self, session_id: UUID) -> AtcRuntimeSession:
        runtime = self.sessions.get(session_id)
        if runtime is None:
            raise KeyError("ATC runtime session not found")
        return runtime
