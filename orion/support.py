from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from orion.mission import MissionPosition


class SupportType(StrEnum):
    AWACS = "awacs"
    TANKER = "tanker"
    LASER_DESIGNATION = "laser_designation"
    SMOKE_MARK = "smoke_mark"


class SupportStatus(StrEnum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    UNAVAILABLE = "unavailable"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SupportRequestCreate(BaseModel):
    support_type: SupportType
    requester: str = Field(min_length=1)
    target_unit_id: str | None = None
    target_position: MissionPosition | None = None
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_target(self) -> "SupportRequestCreate":
        if self.support_type in {SupportType.LASER_DESIGNATION, SupportType.SMOKE_MARK}:
            if self.target_unit_id is None and self.target_position is None:
                raise ValueError("target_unit_id or target_position is required for target marking")
        return self


class SupportRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    support_type: SupportType
    requester: str
    status: SupportStatus = SupportStatus.REQUESTED
    target_unit_id: str | None = None
    target_position: MissionPosition | None = None
    notes: str | None = None
    provider_unit_id: str | None = None
    frequency_mhz: float | None = Field(default=None, gt=0)
    tacan: str | None = None
    laser_code: int | None = Field(default=None, ge=1111, le=1788)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SupportRequestStore:
    def __init__(self) -> None:
        self._requests: dict[UUID, SupportRequest] = {}

    def create(self, payload: SupportRequestCreate) -> SupportRequest:
        request = SupportRequest(**payload.model_dump())
        self._requests[request.request_id] = request
        return request

    def list(self) -> list[SupportRequest]:
        return list(self._requests.values())


support_requests = SupportRequestStore()
