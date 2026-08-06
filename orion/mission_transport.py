from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, Field

from orion.mission_bridge import MissionCommand


class MissionTransportEnvelope(BaseModel):
    session_id: UUID
    sequence: int = Field(ge=1)
    attempt: int = Field(default=1, ge=1)
    command: MissionCommand
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DeliveryRecord(BaseModel):
    envelope: MissionTransportEnvelope
    acknowledged: bool = False
    acknowledged_at: datetime | None = None


class DeliveryTracker:
    def __init__(self) -> None:
        self._lock = RLock()
        self._next_sequence: dict[UUID, int] = {}
        self._records: dict[UUID, DeliveryRecord] = {}

    def create(self, session_id: UUID, command: MissionCommand) -> DeliveryRecord:
        with self._lock:
            sequence = self._next_sequence.get(session_id, 1)
            self._next_sequence[session_id] = sequence + 1
            record = DeliveryRecord(
                envelope=MissionTransportEnvelope(
                    session_id=session_id,
                    sequence=sequence,
                    command=command,
                )
            )
            self._records[command.command_id] = record
            return record

    def acknowledge(self, command_id: UUID) -> DeliveryRecord | None:
        with self._lock:
            record = self._records.get(command_id)
            if record is None:
                return None
            if not record.acknowledged:
                record.acknowledged = True
                record.acknowledged_at = datetime.now(UTC)
            return record

    def retry(self, command_id: UUID) -> DeliveryRecord | None:
        with self._lock:
            record = self._records.get(command_id)
            if record is None or record.acknowledged:
                return None
            record.envelope.attempt += 1
            record.envelope.sent_at = datetime.now(UTC)
            return record

    def pending(self) -> list[DeliveryRecord]:
        with self._lock:
            return [record for record in self._records.values() if not record.acknowledged]


delivery_tracker = DeliveryTracker()
