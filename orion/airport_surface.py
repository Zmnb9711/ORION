from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.atc_operations import FreshnessClass


class RunwayAvailability(StrEnum):
    CLEAR = "clear"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    UNKNOWN = "unknown"
    STALE = "stale"
    CLOSED = "closed"


class CrossingState(StrEnum):
    REQUESTED = "requested"
    HOLD_SHORT = "hold_short"
    CLEARED = "cleared"
    COMMITTED = "committed"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


class SurfaceSegment(BaseModel):
    segment_id: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=160)


class TaxiRoute(BaseModel):
    route_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    facility_id: str = Field(min_length=1, max_length=160)
    origin: str = Field(min_length=1, max_length=160)
    destination: str = Field(min_length=1, max_length=160)
    segments: list[SurfaceSegment] = Field(default_factory=list)
    runway_crossings: list[str] = Field(default_factory=list)
    hold_short_resources: list[str] = Field(default_factory=list)
    topology_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str = Field(min_length=1, max_length=500)


class HoldShortConstraint(BaseModel):
    constraint_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    resource_id: str = Field(min_length=1, max_length=160)
    active: bool = True
    acknowledgement_required: bool = True
    acknowledged: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    released_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)

    def acknowledge(self) -> None:
        if not self.active:
            raise ValueError("Inactive hold-short constraint cannot be acknowledged")
        self.acknowledged = True

    def release(self) -> None:
        if not self.active:
            return
        self.active = False
        self.released_at = datetime.now(UTC)


class RunwayState(BaseModel):
    runway_id: str = Field(min_length=1, max_length=80)
    availability: RunwayAvailability = RunwayAvailability.UNKNOWN
    freshness: FreshnessClass = FreshnessClass.UNKNOWN
    observed_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)

    @property
    def usable_for_positive_clearance(self) -> bool:
        return self.availability is RunwayAvailability.CLEAR and self.freshness in {
            FreshnessClass.FRESH,
            FreshnessClass.AGING,
        }


class RunwayCrossingTransaction(BaseModel):
    crossing_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    runway_id: str = Field(min_length=1, max_length=80)
    state: CrossingState = CrossingState.REQUESTED
    acknowledgement_required: bool = True
    acknowledged: bool = False
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cleared_at: datetime | None = None
    committed_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)

    def hold_short(self) -> None:
        if self.state not in {CrossingState.REQUESTED, CrossingState.HOLD_SHORT}:
            raise ValueError("Crossing cannot return to hold-short from current state")
        self.state = CrossingState.HOLD_SHORT

    def clear(self, runway: RunwayState) -> None:
        if self.state not in {CrossingState.REQUESTED, CrossingState.HOLD_SHORT}:
            raise ValueError("Crossing is not clearable")
        if not runway.usable_for_positive_clearance:
            raise ValueError("Runway state is not safe enough for positive crossing clearance")
        self.state = CrossingState.CLEARED
        self.cleared_at = datetime.now(UTC)

    def acknowledge(self) -> None:
        if self.state is not CrossingState.CLEARED:
            raise ValueError("Crossing clearance is not awaiting acknowledgement")
        self.acknowledged = True

    def commit(self) -> None:
        if self.state is not CrossingState.CLEARED:
            raise ValueError("Crossing is not cleared")
        if self.acknowledgement_required and not self.acknowledged:
            raise ValueError("Crossing clearance must be acknowledged before commitment")
        self.state = CrossingState.COMMITTED
        self.committed_at = datetime.now(UTC)

    def complete(self) -> None:
        if self.state is not CrossingState.COMMITTED:
            raise ValueError("Only a committed crossing can complete")
        self.state = CrossingState.COMPLETE
        self.completed_at = datetime.now(UTC)

    def cancel(self) -> None:
        if self.state is CrossingState.COMMITTED:
            raise ValueError("Physically committed crossing cannot be normally cancelled")
        if self.state in {CrossingState.COMPLETE, CrossingState.CANCELLED}:
            raise ValueError("Crossing is already final")
        self.state = CrossingState.CANCELLED
        self.cancelled_at = datetime.now(UTC)
