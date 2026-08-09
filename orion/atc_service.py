from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from orion.atc_core import (
    AtcSessionIdentity,
    ControllerAgency,
    ControllerAuthorityScope,
    ControllerHandoffTransaction,
    HandoffTransferMode,
)
from orion.atc_integration import AtcIntegratedRuntime
from orion.atc_operations import OperationalOverlay
from orion.atc_simulator_sync import AtcIntegrationMode, NativeActionRequest


class AtcStatusSnapshot(BaseModel):
    session_id: UUID
    mission_id: str
    aircraft_id: str
    facility_id: str | None = None
    procedural_state: str
    overlays: list[OperationalOverlay] = Field(default_factory=list)
    integration_mode: AtcIntegrationMode
    authority: dict[ControllerAuthorityScope, ControllerAgency] = Field(default_factory=dict)
    pending_instruction_count: int = 0
    native_sync_requests: list[NativeActionRequest] = Field(default_factory=list)
    event_count: int = 0


class VirtualAtcService(AtcIntegratedRuntime):
    """Application-level Virtual ATC facade for carrier and fixed-airfield engines."""

    def begin_event_gated_handoff(
        self,
        *,
        session_id: UUID,
        source: ControllerAgency,
        destination: ControllerAgency,
        scopes: list[ControllerAuthorityScope],
        reason: str,
        frequency: str | None = None,
        channel: str | None = None,
    ) -> ControllerHandoffTransaction:
        runtime = self._require_session(session_id)
        handoff = self.core.authority.begin_handoff(
            session_id=session_id,
            source_agency=source,
            destination_agency=destination,
            scopes=scopes,
            transfer_mode=HandoffTransferMode.EVENT_GATED_IRREVERSIBLE,
            reason=reason,
            frequency=frequency,
            channel=channel,
        )
        self.core.history.record(
            session_id=session_id,
            event_type="handoff_started",
            reason=reason,
            source_agency=source,
            related_id=handoff.handoff_id,
            details={
                "destination": destination.value,
                "transfer_mode": handoff.transfer_mode.value,
                "scopes": ",".join(scope.value for scope in handoff.scopes),
                "procedural_state": runtime.procedural_state,
            },
        )
        return handoff

    def complete_event_gated_handoff(
        self,
        handoff_id: UUID,
        *,
        event_name: str,
        reason: str,
        contact_established: bool | None = None,
    ) -> ControllerHandoffTransaction:
        handoff = self.core.authority.get_handoff(handoff_id)
        if handoff is None:
            raise KeyError("ATC handoff not found")
        self._require_session(handoff.session_id)
        if handoff.transfer_mode is not HandoffTransferMode.EVENT_GATED_IRREVERSIBLE:
            raise ValueError("Handoff is not event-gated irreversible")
        completed = self.core.authority.complete_handoff(
            handoff_id,
            contact_established=contact_established,
        )
        self.core.history.record(
            session_id=completed.session_id,
            event_type="handoff_completed_on_event",
            reason=reason,
            source_agency=completed.destination_agency,
            related_id=completed.handoff_id,
            details={
                "event_name": event_name,
                "source": completed.source_agency.value,
                "destination": completed.destination_agency.value,
                "scopes": ",".join(scope.value for scope in completed.scopes),
            },
        )
        return completed

    def close_session(self, session_id: UUID, *, reason: str) -> AtcSessionIdentity:
        runtime = self._require_session(session_id)
        identity = runtime.identity.model_copy(deep=True)
        self.core.history.record(
            session_id=session_id,
            event_type="session_closed",
            reason=reason,
            details={
                "procedural_state": runtime.procedural_state,
                "integration_mode": self.get_integration_mode(session_id).value,
            },
        )
        self.core.authority.clear_session(session_id)
        self.core.instructions.clear_session(session_id)
        self.simulator_sync.clear_session(session_id)
        self.sessions.remove(session_id)
        self._integration_modes.pop(session_id, None)
        return identity

    def status(self, session_id: UUID) -> AtcStatusSnapshot:
        runtime = self._require_session(session_id)
        ownership = self.core.authority.list_ownership(session_id)
        instructions = self.core.instructions.list_session(session_id)
        native_sync = self.simulator_sync.list_session(session_id)
        events = self.core.history.list(session_id)
        return AtcStatusSnapshot(
            session_id=session_id,
            mission_id=runtime.identity.mission_id,
            aircraft_id=runtime.identity.aircraft_id,
            facility_id=runtime.identity.facility_id,
            procedural_state=runtime.procedural_state,
            overlays=sorted(runtime.overlays, key=lambda value: value.value),
            integration_mode=self.get_integration_mode(session_id),
            authority={item.scope: item.agency for item in ownership},
            pending_instruction_count=sum(
                1
                for item in instructions
                if item.state.value in {"pending", "transmitted"}
            ),
            native_sync_requests=native_sync,
            event_count=len(events),
        )


virtual_atc = VirtualAtcService()
