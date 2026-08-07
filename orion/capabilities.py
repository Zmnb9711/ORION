from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock

from pydantic import BaseModel, Field


class MissionCapability(StrEnum):
    LASER = "laser"
    SMOKE = "smoke"
    AWACS = "awacs"
    TANKER = "tanker"
    TASKING = "tasking"
    ARTILLERY = "artillery"
    CSAR = "csar"


class MissionPackRegistration(BaseModel):
    mission_id: str = Field(min_length=1)
    pack_version: str = Field(min_length=1)
    protocol_version: str = "0.2"
    capabilities: set[MissionCapability] = Field(default_factory=set)
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CapabilityRegistry:
    def __init__(self) -> None:
        self._registration: MissionPackRegistration | None = None
        self._lock = Lock()

    def register(self, registration: MissionPackRegistration) -> None:
        with self._lock:
            self._registration = registration

    def get(self) -> MissionPackRegistration | None:
        with self._lock:
            return self._registration

    def supports(self, capability: MissionCapability) -> bool:
        registration = self.get()
        return registration is not None and capability in registration.capabilities


capability_registry = CapabilityRegistry()
