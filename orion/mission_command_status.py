from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from uuid import UUID

from pydantic import BaseModel, Field


class MissionCommandStatus(StrEnum):
    QUEUED = "queued"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    FAILED = "failed"


class MissionCommandResult(BaseModel):
    command_id: UUID
    status: MissionCommandStatus
    message: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MissionCommandStatusStore:
    def __init__(self) -> None:
        self._items: dict[UUID, MissionCommandResult] = {}
        self._lock = Lock()

    def set(
        self,
        command_id: UUID,
        status: MissionCommandStatus,
        message: str | None = None,
    ) -> MissionCommandResult:
        result = MissionCommandResult(
            command_id=command_id,
            status=status,
            message=message,
        )
        with self._lock:
            self._items[command_id] = result
        return result

    def get(self, command_id: UUID) -> MissionCommandResult | None:
        with self._lock:
            return self._items.get(command_id)

    def list(self) -> list[MissionCommandResult]:
        with self._lock:
            return sorted(
                self._items.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            )


mission_command_statuses = MissionCommandStatusStore()
