from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.atc_operations import CapabilitySupport


class AtcIntegrationMode(StrEnum):
    ORION_PRIMARY = "orion_primary"
    ORION_WITH_NATIVE_FALLBACK = "orion_with_native_fallback"
    NATIVE_FALLBACK = "native_fallback"


class NativeSyncState(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    UNKNOWN = "unknown"


class NativeActionRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    semantic_action: str = Field(min_length=1, max_length=160)
    adapter_kind: str = Field(min_length=1, max_length=80)
    capability: CapabilitySupport = CapabilitySupport.UNKNOWN
    state: NativeSyncState = NativeSyncState.PENDING
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)


class AtcSimulatorSyncRegistry:
    """Domain-neutral registry for native DCS synchronization attempts/results."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[UUID, NativeActionRequest] = {}

    def create(self, request: NativeActionRequest) -> NativeActionRequest:
        with self._lock:
            if request.request_id in self._items:
                raise ValueError("Native ATC sync request already exists")
            self._items[request.request_id] = request.model_copy(deep=True)
            return request.model_copy(deep=True)

    def get(self, request_id: UUID) -> NativeActionRequest | None:
        with self._lock:
            item = self._items.get(request_id)
            return item.model_copy(deep=True) if item else None

    def list_session(self, session_id: UUID) -> list[NativeActionRequest]:
        with self._lock:
            items = [item for item in self._items.values() if item.session_id == session_id]
            return [item.model_copy(deep=True) for item in sorted(items, key=lambda value: value.issued_at)]

    def resolve(
        self,
        request_id: UUID,
        *,
        state: NativeSyncState,
        capability: CapabilitySupport | None = None,
        reason: str,
    ) -> NativeActionRequest:
        if state is NativeSyncState.PENDING:
            raise ValueError("Resolved native sync state cannot remain pending")
        with self._lock:
            item = self._items.get(request_id)
            if item is None:
                raise KeyError("Native ATC sync request not found")
            if item.state is not NativeSyncState.PENDING:
                raise ValueError("Native ATC sync request is already final")
            item.state = state
            if capability is not None:
                item.capability = capability
            item.completed_at = datetime.now(UTC)
            item.reason = reason
            return item.model_copy(deep=True)

    def clear_session(self, session_id: UUID) -> None:
        with self._lock:
            for request_id in [
                item.request_id for item in self._items.values() if item.session_id == session_id
            ]:
                self._items.pop(request_id, None)
