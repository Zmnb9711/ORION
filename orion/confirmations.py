from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from uuid import uuid4

from pydantic import BaseModel, Field


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class PendingActionCreate(BaseModel):
    action_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


class PendingAction(BaseModel):
    action_id: str
    action_type: str
    summary: str
    payload: dict
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None


class ConfirmationDecision(BaseModel):
    confirm: bool


class ConfirmationStore:
    def __init__(self) -> None:
        self._items: dict[str, PendingAction] = {}
        self._lock = Lock()

    def create(self, payload: PendingActionCreate) -> PendingAction:
        item = PendingAction(action_id=str(uuid4()), **payload.model_dump())
        with self._lock:
            self._items[item.action_id] = item
        return item

    def get(self, action_id: str) -> PendingAction | None:
        with self._lock:
            return self._items.get(action_id)

    def list(self, status: ConfirmationStatus | None = None) -> list[PendingAction]:
        with self._lock:
            values = list(self._items.values())
        if status is not None:
            values = [item for item in values if item.status == status]
        return sorted(values, key=lambda item: item.created_at)

    def resolve(self, action_id: str, confirm: bool) -> PendingAction | None:
        with self._lock:
            item = self._items.get(action_id)
            if item is None or item.status != ConfirmationStatus.PENDING:
                return None
            resolved = item.model_copy(
                update={
                    "status": ConfirmationStatus.CONFIRMED if confirm else ConfirmationStatus.REJECTED,
                    "resolved_at": datetime.now(UTC),
                }
            )
            self._items[action_id] = resolved
            return resolved


confirmation_store = ConfirmationStore()
