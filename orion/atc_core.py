from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ControllerAgency(StrEnum):
    AIRPORT_CLEARANCE_DELIVERY = "airport_clearance_delivery"
    AIRPORT_GROUND = "airport_ground"
    AIRPORT_TOWER = "airport_tower"
    AIRPORT_DEPARTURE = "airport_departure"
    AIRPORT_APPROACH = "airport_approach"
    AIRPORT_PAR = "airport_par"
    CARRIER_AIR_BOSS = "carrier_air_boss"
    CARRIER_DEPARTURE = "carrier_departure"
    CARRIER_MARSHAL = "carrier_marshal"
    CARRIER_APPROACH = "carrier_approach"
    CARRIER_TOWER = "carrier_tower"
    CARRIER_LSO = "carrier_lso"
    CARRIER_DECK = "carrier_deck"
    MISSION_CONTROL = "mission_control"


class ControllerAuthorityScope(StrEnum):
    ROUTE_CLEARANCE = "route_clearance"
    SURFACE_MOVEMENT = "surface_movement"
    DECK_RESOURCE = "deck_resource"
    FLIGHT_TRAFFIC = "flight_traffic"
    LANDING_AREA = "landing_area"
    FINAL_GUIDANCE = "final_guidance"
    MISSION_TACTICAL = "mission_tactical"


class HandoffTransferMode(StrEnum):
    ACKNOWLEDGEMENT_GATED = "acknowledgement_gated"
    EVENT_GATED_IRREVERSIBLE = "event_gated_irreversible"


class HandoffState(StrEnum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContactState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    ESTABLISHED = "established"
    LOST = "lost"


class AtcSessionIdentity(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    mission_id: str = Field(min_length=1, max_length=160)
    aircraft_id: str = Field(min_length=1, max_length=160)
    facility_id: str | None = Field(default=None, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ControllerOwnership(BaseModel):
    session_id: UUID
    scope: ControllerAuthorityScope
    agency: ControllerAgency
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str = Field(min_length=1, max_length=500)


class ControllerHandoffTransaction(BaseModel):
    handoff_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    source_agency: ControllerAgency
    destination_agency: ControllerAgency
    scopes: list[ControllerAuthorityScope] = Field(min_length=1)
    transfer_mode: HandoffTransferMode
    reason: str = Field(min_length=1, max_length=500)
    frequency: str | None = Field(default=None, max_length=80)
    channel: str | None = Field(default=None, max_length=80)
    state: HandoffState = HandoffState.PENDING
    contact_state: ContactState = ContactState.PENDING
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    acknowledged_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = Field(default=None, max_length=500)


class AtcAuthorityRegistry:
    """Thread-safe, mission/session-scoped ownership and handoff authority registry."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._ownership: dict[tuple[UUID, ControllerAuthorityScope], ControllerOwnership] = {}
        self._handoffs: dict[UUID, ControllerHandoffTransaction] = {}

    def claim(
        self,
        *,
        session_id: UUID,
        scope: ControllerAuthorityScope,
        agency: ControllerAgency,
        reason: str,
        replace_same_agency: bool = True,
    ) -> ControllerOwnership:
        with self._lock:
            key = (session_id, scope)
            current = self._ownership.get(key)
            if current is not None and current.agency is not agency:
                raise ValueError(
                    f"Authority scope {scope.value} for session {session_id} is already owned by "
                    f"{current.agency.value}"
                )
            if current is not None and not replace_same_agency:
                raise ValueError(f"Authority scope {scope.value} is already claimed")
            ownership = ControllerOwnership(
                session_id=session_id,
                scope=scope,
                agency=agency,
                reason=reason,
            )
            self._ownership[key] = ownership
            return ownership.model_copy(deep=True)

    def get_owner(
        self,
        session_id: UUID,
        scope: ControllerAuthorityScope,
    ) -> ControllerOwnership | None:
        with self._lock:
            item = self._ownership.get((session_id, scope))
            return item.model_copy(deep=True) if item else None

    def list_ownership(self, session_id: UUID) -> list[ControllerOwnership]:
        with self._lock:
            items = [item for (sid, _), item in self._ownership.items() if sid == session_id]
            return [item.model_copy(deep=True) for item in sorted(items, key=lambda value: value.scope.value)]

    def release(
        self,
        *,
        session_id: UUID,
        scope: ControllerAuthorityScope,
        agency: ControllerAgency | None = None,
    ) -> ControllerOwnership | None:
        with self._lock:
            key = (session_id, scope)
            current = self._ownership.get(key)
            if current is None:
                return None
            if agency is not None and current.agency is not agency:
                raise ValueError(
                    f"Cannot release {scope.value}: current owner is {current.agency.value}, not {agency.value}"
                )
            removed = self._ownership.pop(key)
            return removed.model_copy(deep=True)

    def begin_handoff(
        self,
        *,
        session_id: UUID,
        source_agency: ControllerAgency,
        destination_agency: ControllerAgency,
        scopes: list[ControllerAuthorityScope],
        transfer_mode: HandoffTransferMode,
        reason: str,
        frequency: str | None = None,
        channel: str | None = None,
    ) -> ControllerHandoffTransaction:
        with self._lock:
            normalized_scopes = list(dict.fromkeys(scopes))
            if not normalized_scopes:
                raise ValueError("Handoff requires at least one authority scope")
            for scope in normalized_scopes:
                current = self._ownership.get((session_id, scope))
                if current is None:
                    raise ValueError(f"Cannot hand off unowned scope {scope.value}")
                if current.agency is not source_agency:
                    raise ValueError(
                        f"Cannot hand off {scope.value}: current owner is {current.agency.value}, "
                        f"not {source_agency.value}"
                    )
            handoff = ControllerHandoffTransaction(
                session_id=session_id,
                source_agency=source_agency,
                destination_agency=destination_agency,
                scopes=normalized_scopes,
                transfer_mode=transfer_mode,
                reason=reason,
                frequency=frequency,
                channel=channel,
            )
            self._handoffs[handoff.handoff_id] = handoff
            return handoff.model_copy(deep=True)

    def acknowledge_handoff(self, handoff_id: UUID) -> ControllerHandoffTransaction:
        with self._lock:
            handoff = self._require_open_handoff(handoff_id)
            if handoff.state is not HandoffState.PENDING:
                raise ValueError("Handoff is not pending acknowledgement")
            handoff.state = HandoffState.ACKNOWLEDGED
            handoff.contact_state = ContactState.ESTABLISHED
            handoff.acknowledged_at = datetime.now(UTC)
            return handoff.model_copy(deep=True)

    def complete_handoff(
        self,
        handoff_id: UUID,
        *,
        contact_established: bool | None = None,
    ) -> ControllerHandoffTransaction:
        with self._lock:
            handoff = self._require_open_handoff(handoff_id)
            if handoff.transfer_mode is HandoffTransferMode.ACKNOWLEDGEMENT_GATED:
                if handoff.state is not HandoffState.ACKNOWLEDGED:
                    raise ValueError("Acknowledgement-gated handoff must be acknowledged before completion")
            elif handoff.state not in {HandoffState.PENDING, HandoffState.ACKNOWLEDGED}:
                raise ValueError("Event-gated handoff is not transferable")

            for scope in handoff.scopes:
                current = self._ownership.get((handoff.session_id, scope))
                if current is None or current.agency is not handoff.source_agency:
                    raise ValueError(f"Source no longer owns scope {scope.value}")

            now = datetime.now(UTC)
            for scope in handoff.scopes:
                self._ownership[(handoff.session_id, scope)] = ControllerOwnership(
                    session_id=handoff.session_id,
                    scope=scope,
                    agency=handoff.destination_agency,
                    reason=f"Handoff {handoff.handoff_id}: {handoff.reason}",
                    acquired_at=now,
                )

            if contact_established is True:
                handoff.contact_state = ContactState.ESTABLISHED
                handoff.acknowledged_at = handoff.acknowledged_at or now
            elif contact_established is False:
                handoff.contact_state = ContactState.PENDING
            handoff.state = HandoffState.COMPLETED
            handoff.completed_at = now
            return handoff.model_copy(deep=True)

    def fail_handoff(self, handoff_id: UUID, reason: str) -> ControllerHandoffTransaction:
        with self._lock:
            handoff = self._require_open_handoff(handoff_id)
            handoff.state = HandoffState.FAILED
            handoff.failure_reason = reason
            return handoff.model_copy(deep=True)

    def get_handoff(self, handoff_id: UUID) -> ControllerHandoffTransaction | None:
        with self._lock:
            item = self._handoffs.get(handoff_id)
            return item.model_copy(deep=True) if item else None

    def clear_session(self, session_id: UUID) -> None:
        with self._lock:
            for key in [key for key in self._ownership if key[0] == session_id]:
                self._ownership.pop(key, None)
            for handoff in self._handoffs.values():
                if handoff.session_id == session_id and handoff.state in {
                    HandoffState.PENDING,
                    HandoffState.ACKNOWLEDGED,
                }:
                    handoff.state = HandoffState.CANCELLED
                    handoff.failure_reason = "ATC session cleared"

    def _require_open_handoff(self, handoff_id: UUID) -> ControllerHandoffTransaction:
        handoff = self._handoffs.get(handoff_id)
        if handoff is None:
            raise KeyError("ATC handoff not found")
        if handoff.state in {HandoffState.COMPLETED, HandoffState.FAILED, HandoffState.CANCELLED}:
            raise ValueError("ATC handoff is already final")
        return handoff


atc_authority = AtcAuthorityRegistry()
