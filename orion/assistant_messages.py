from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AssistantMessagePriority(IntEnum):
    LOW = 10
    NORMAL = 20
    HIGH = 30
    CRITICAL = 40


class AssistantMessageState(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AssistantMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    source: str = Field(min_length=1, max_length=120)
    session_id: str | None = Field(default=None, max_length=160)
    command_id: str | None = Field(default=None, max_length=160)
    correlation_id: str | None = Field(default=None, max_length=160)
    priority: AssistantMessagePriority = AssistantMessagePriority.NORMAL
    speak: bool = True
    show_in_console: bool = True
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class AssistantMessage(BaseModel):
    message_id: UUID = Field(default_factory=uuid4)
    text: str
    source: str
    session_id: str | None = None
    command_id: str | None = None
    correlation_id: str | None = None
    priority: AssistantMessagePriority
    speak: bool
    show_in_console: bool
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    state: AssistantMessageState = AssistantMessageState.QUEUED
    claimed_by: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AssistantMessageQueue:
    """Single delivery queue shared by speech output and Flight Console.

    Correlation ids provide idempotency: retrying the same completed knowledge follow-up
    does not create a second spoken response.
    """

    def __init__(self) -> None:
        self._items: dict[UUID, AssistantMessage] = {}
        self._correlations: dict[str, UUID] = {}
        self._lock = RLock()

    def enqueue(self, payload: AssistantMessageCreate) -> AssistantMessage:
        with self._lock:
            if payload.correlation_id:
                existing_id = self._correlations.get(payload.correlation_id)
                if existing_id is not None:
                    return self._items[existing_id].model_copy(deep=True)
            item = AssistantMessage(**payload.model_dump())
            self._items[item.message_id] = item
            if item.correlation_id:
                self._correlations[item.correlation_id] = item.message_id
            return item.model_copy(deep=True)

    def list(self, *, state: AssistantMessageState | None = None) -> list[AssistantMessage]:
        with self._lock:
            values = [item for item in self._items.values() if state is None or item.state is state]
            values.sort(key=lambda item: (-int(item.priority), item.created_at))
            return [item.model_copy(deep=True) for item in values]

    def get(self, message_id: UUID) -> AssistantMessage | None:
        with self._lock:
            item = self._items.get(message_id)
            return item.model_copy(deep=True) if item else None

    def claim_next(self, consumer: str, *, speech_only: bool = False) -> AssistantMessage | None:
        with self._lock:
            candidates = [
                item for item in self._items.values()
                if item.state is AssistantMessageState.QUEUED and (item.speak or not speech_only)
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda item: (-int(item.priority), item.created_at))
            item = candidates[0]
            item.state = AssistantMessageState.CLAIMED
            item.claimed_by = consumer
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)

    def delivered(self, message_id: UUID, consumer: str) -> AssistantMessage:
        with self._lock:
            item = self._items[message_id]
            if item.state is AssistantMessageState.DELIVERED:
                return item.model_copy(deep=True)
            if item.state is not AssistantMessageState.CLAIMED or item.claimed_by != consumer:
                raise ValueError("Message must be claimed by this consumer before delivery")
            item.state = AssistantMessageState.DELIVERED
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)

    def release(self, message_id: UUID, consumer: str, *, error: str | None = None) -> AssistantMessage:
        with self._lock:
            item = self._items[message_id]
            if item.state is not AssistantMessageState.CLAIMED or item.claimed_by != consumer:
                raise ValueError("Message is not claimed by this consumer")
            item.state = AssistantMessageState.QUEUED
            item.claimed_by = None
            item.error = error
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)

    def fail(self, message_id: UUID, error: str) -> AssistantMessage:
        with self._lock:
            item = self._items[message_id]
            item.state = AssistantMessageState.FAILED
            item.error = error
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)

    def cancel(self, message_id: UUID) -> AssistantMessage:
        with self._lock:
            item = self._items[message_id]
            if item.state is AssistantMessageState.DELIVERED:
                raise ValueError("Delivered message cannot be cancelled")
            item.state = AssistantMessageState.CANCELLED
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)


assistant_messages = AssistantMessageQueue()
