from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.atc_core import ControllerAgency, ControllerAuthorityScope


class AcknowledgementState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    EXPIRED = "expired"


class InstructionState(StrEnum):
    PENDING = "pending"
    TRANSMITTED = "transmitted"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class VoicePriority(IntEnum):
    FREE_FORM = 10
    ADVISORY = 20
    NORMAL = 30
    PROCEDURAL = 40
    CRITICAL_FUEL = 60
    EMERGENCY = 80
    IMMEDIATE_SAFETY = 100


class TrafficPriority(IntEnum):
    NORMAL = 10
    PROTECTED_SLOT = 20
    COMMITTED_TRAFFIC = 40
    CRITICAL_FUEL = 80
    EMERGENCY = 100


class CommitmentState(IntEnum):
    UNCOMMITTED = 0
    RESERVED = 10
    PROCEDURALLY_COMMITTED = 20
    PHYSICALLY_COMMITTED = 30
    IRREVERSIBLE = 40


class CapabilitySupport(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class FreshnessClass(StrEnum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    UNKNOWN = "unknown"


class OperationalOverlay(StrEnum):
    EMERGENCY = "emergency"
    CRITICAL_FUEL = "critical_fuel"
    BINGO_DIVERT_REQUIRED = "bingo_divert_required"
    LOST_COMMS_SUSPECTED = "lost_comms_suspected"
    LOST_COMMS_CONFIRMED = "lost_comms_confirmed"
    HANDOFF_DEGRADED = "handoff_degraded"
    TELEMETRY_STALE = "telemetry_stale"
    NAV_AID_DEGRADED = "nav_aid_degraded"
    RECOVERY_SUSPENDED_AFFECTED = "recovery_suspended_affected"


class CapabilityValue(BaseModel):
    support: CapabilitySupport
    value: Any | None = None
    source: str | None = Field(default=None, max_length=160)
    observed_at: datetime | None = None
    freshness: FreshnessClass = FreshnessClass.UNKNOWN
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def usable_for_positive_assertion(self) -> bool:
        return (
            self.support is CapabilitySupport.SUPPORTED
            and self.value is not None
            and self.freshness is not FreshnessClass.STALE
        )


class OperationalInstruction(BaseModel):
    instruction_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    issuing_agency: ControllerAgency
    authority_scope: ControllerAuthorityScope
    semantic_action: str = Field(min_length=1, max_length=160)
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    acknowledgement_required: bool = True
    acknowledgement_state: AcknowledgementState = AcknowledgementState.PENDING
    state: InstructionState = InstructionState.PENDING
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=2, ge=0, le=10)
    voice_priority: VoicePriority = VoicePriority.PROCEDURAL
    stale_reason: str | None = Field(default=None, max_length=500)

    def mark_transmitted(self) -> None:
        if self.state in {
            InstructionState.ACKNOWLEDGED,
            InstructionState.REJECTED,
            InstructionState.EXPIRED,
            InstructionState.CANCELLED,
        }:
            raise ValueError("Final instruction cannot be retransmitted")
        self.state = InstructionState.TRANSMITTED
        if not self.acknowledgement_required:
            self.acknowledgement_state = AcknowledgementState.NOT_REQUIRED

    def acknowledge(self) -> None:
        if not self.acknowledgement_required:
            raise ValueError("Instruction does not require acknowledgement")
        if self.state in {InstructionState.EXPIRED, InstructionState.CANCELLED}:
            raise ValueError("Final instruction cannot be acknowledged")
        self.acknowledgement_state = AcknowledgementState.ACKNOWLEDGED
        self.state = InstructionState.ACKNOWLEDGED

    def reject(self) -> None:
        if self.state in {InstructionState.EXPIRED, InstructionState.CANCELLED}:
            raise ValueError("Final instruction cannot be rejected")
        self.acknowledgement_state = AcknowledgementState.REJECTED
        self.state = InstructionState.REJECTED

    def retry(self) -> None:
        if self.state not in {InstructionState.PENDING, InstructionState.TRANSMITTED}:
            raise ValueError("Instruction is not retryable")
        if self.retry_count >= self.max_retries:
            raise ValueError("Instruction retry limit reached")
        self.retry_count += 1
        self.state = InstructionState.PENDING

    def expire_if_due(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = now or datetime.now(UTC)
        if current < self.expires_at:
            return False
        if self.state in {
            InstructionState.ACKNOWLEDGED,
            InstructionState.REJECTED,
            InstructionState.EXPIRED,
            InstructionState.CANCELLED,
        }:
            return False
        self.state = InstructionState.EXPIRED
        self.acknowledgement_state = AcknowledgementState.EXPIRED
        return True


class SequencedTrafficEntry(BaseModel):
    session_id: UUID
    priority: TrafficPriority = TrafficPriority.NORMAL
    commitment: CommitmentState = CommitmentState.UNCOMMITTED
    sequence_index: int = Field(ge=0)
    predecessor_session_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=500)
    revision: int = Field(default=1, ge=1)


class EmergencyState(BaseModel):
    active: bool = False
    declared_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)


class DivertPlan(BaseModel):
    plan_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    reason: str = Field(min_length=1, max_length=500)
    destination_id: str | None = Field(default=None, max_length=160)
    route: str | None = Field(default=None, max_length=500)
    frequency: str | None = Field(default=None, max_length=80)
    acknowledged: bool = False
    revision: int = Field(default=1, ge=1)


class TrafficConflict(BaseModel):
    conflict_id: UUID = Field(default_factory=uuid4)
    class_name: str = Field(min_length=1, max_length=160)
    sessions: list[UUID] = Field(min_length=1)
    severity: VoicePriority = VoicePriority.PROCEDURAL
    reason: str = Field(min_length=1, max_length=500)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResourceAssignment(BaseModel):
    assignment_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    resource_type: str = Field(min_length=1, max_length=80)
    resource_id: str = Field(min_length=1, max_length=160)
    revision: int = Field(default=1, ge=1)
    reason: str = Field(min_length=1, max_length=500)
