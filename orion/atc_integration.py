from __future__ import annotations

from uuid import UUID

from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import (
    CapabilitySupport,
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
from orion.atc_simulator_sync import (
    AtcIntegrationMode,
    AtcSimulatorSyncRegistry,
    NativeActionRequest,
    NativeSyncState,
)


class AtcIntegratedRuntime:
    """Single facade that keeps ATC runtime, native sync and audit history consistent."""

    def __init__(self) -> None:
        self.core = AtcCoreFlow()
        self.sessions = AtcSessionRuntimeStore()
        self.sequencing = GenericSequencingPolicy()
        self.conflicts = GenericConflictResolutionPolicy()
        self.simulator_sync = AtcSimulatorSyncRegistry()
        self._integration_modes: dict[UUID, AtcIntegrationMode] = {}

    def open_session(
        self,
        identity: AtcSessionIdentity,
        *,
        procedural_state: str,
        integration_mode: AtcIntegrationMode = AtcIntegrationMode.ORION_PRIMARY,
    ) -> AtcRuntimeSession:
        runtime = AtcRuntimeSession(identity=identity, procedural_state=procedural_state)
        created = self.sessions.create(runtime)
        self._integration_modes[identity.session_id] = integration_mode
        self.core.open_session(identity)
        self.core.history.record(
            session_id=identity.session_id,
            event_type="procedural_state_initialized",
            reason="initial ATC procedural state",
            details={"procedural_state": procedural_state, "revision": created.revision},
        )
        self.core.history.record(
            session_id=identity.session_id,
            event_type="integration_mode_initialized",
            reason="ATC integration mode initialized",
            details={"integration_mode": integration_mode.value},
        )
        return created

    def get_integration_mode(self, session_id: UUID) -> AtcIntegrationMode:
        self._require_session(session_id)
        return self._integration_modes[session_id]

    def set_integration_mode(
        self,
        session_id: UUID,
        mode: AtcIntegrationMode,
        *,
        reason: str,
    ) -> AtcIntegrationMode:
        self._require_session(session_id)
        previous = self._integration_modes[session_id]
        self._integration_modes[session_id] = mode
        self.core.history.record(
            session_id=session_id,
            event_type="integration_mode_changed",
            reason=reason,
            details={"previous": previous.value, "current": mode.value},
        )
        return mode

    def request_native_sync(
        self,
        *,
        session_id: UUID,
        semantic_action: str,
        adapter_kind: str,
        capability: CapabilitySupport,
        reason: str,
        details: dict[str, str | int | float | bool] | None = None,
    ) -> NativeActionRequest:
        runtime = self._require_session(session_id)
        request = self.simulator_sync.create(
            NativeActionRequest(
                session_id=session_id,
                semantic_action=semantic_action,
                adapter_kind=adapter_kind,
                capability=capability,
                reason=reason,
                details=details or {},
            )
        )
        self.core.history.record(
            session_id=session_id,
            event_type="native_sync_requested",
            reason=reason,
            related_id=request.request_id,
            details={
                "semantic_action": semantic_action,
                "adapter_kind": adapter_kind,
                "capability": capability.value,
                "procedural_state": runtime.procedural_state,
            },
        )
        return request

    def resolve_native_sync(
        self,
        request_id: UUID,
        *,
        state: NativeSyncState,
        reason: str,
        capability: CapabilitySupport | None = None,
    ) -> NativeActionRequest:
        current = self.simulator_sync.get(request_id)
        if current is None:
            raise KeyError("Native ATC sync request not found")
        runtime = self._require_session(current.session_id)
        resolved = self.simulator_sync.resolve(
            request_id,
            state=state,
            capability=capability,
            reason=reason,
        )
        self.core.history.record(
            session_id=resolved.session_id,
            event_type="native_sync_resolved",
            reason=reason,
            related_id=resolved.request_id,
            details={
                "semantic_action": resolved.semantic_action,
                "adapter_kind": resolved.adapter_kind,
                "state": resolved.state.value,
                "capability": resolved.capability.value,
                "procedural_state": runtime.procedural_state,
            },
        )

        if state is NativeSyncState.CONFIRMED:
            if OperationalOverlay.SIMULATOR_SYNC_DEGRADED in runtime.overlays:
                runtime.remove_overlay(
                    OperationalOverlay.SIMULATOR_SYNC_DEGRADED,
                    reason="native simulator synchronization restored",
                )
                self.sessions.replace(runtime)
                self.core.history.record(
                    session_id=resolved.session_id,
                    event_type="simulator_sync_degradation_cleared",
                    reason="native simulator synchronization restored",
                    related_id=resolved.request_id,
                    details={"procedural_state": runtime.procedural_state},
                )
            return resolved

        runtime.add_overlay(
            OperationalOverlay.SIMULATOR_SYNC_DEGRADED,
            reason=reason,
        )
        self.sessions.replace(runtime)

        previous_mode = self._integration_modes[resolved.session_id]
        if state in {NativeSyncState.FAILED, NativeSyncState.UNSUPPORTED}:
            next_mode = AtcIntegrationMode.ORION_WITH_NATIVE_FALLBACK
        else:
            next_mode = previous_mode
        if next_mode is not previous_mode:
            self.set_integration_mode(resolved.session_id, next_mode, reason=reason)

        self.core.history.record(
            session_id=resolved.session_id,
            event_type="simulator_sync_degraded",
            reason=reason,
            related_id=resolved.request_id,
            details={
                "state": state.value,
                "integration_mode": self._integration_modes[resolved.session_id].value,
                "procedural_state": runtime.procedural_state,
            },
        )
        return resolved

    def require_native_fallback(self, session_id: UUID, *, reason: str) -> AtcIntegrationMode:
        runtime = self._require_session(session_id)
        if OperationalOverlay.SIMULATOR_SYNC_DEGRADED not in runtime.overlays:
            runtime.add_overlay(OperationalOverlay.SIMULATOR_SYNC_DEGRADED, reason=reason)
            self.sessions.replace(runtime)
        return self.set_integration_mode(
            session_id,
            AtcIntegrationMode.NATIVE_FALLBACK,
            reason=reason,
        )

    def restore_orion_primary(self, session_id: UUID, *, reason: str) -> AtcIntegrationMode:
        runtime = self._require_session(session_id)
        if OperationalOverlay.SIMULATOR_SYNC_DEGRADED in runtime.overlays:
            runtime.remove_overlay(OperationalOverlay.SIMULATOR_SYNC_DEGRADED, reason=reason)
            self.sessions.replace(runtime)
        return self.set_integration_mode(
            session_id,
            AtcIntegrationMode.ORION_PRIMARY,
            reason=reason,
        )

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
