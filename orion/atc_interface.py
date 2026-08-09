from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from orion.atc_operations import CapabilitySupport


class AtcIntegrationMode(StrEnum):
    ORION_PRIMARY = "orion_primary"
    ORION_WITH_NATIVE_FALLBACK = "orion_with_native_fallback"
    NATIVE_FALLBACK = "native_fallback"


class NativeSyncState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class NativeAtcSyncResult(BaseModel):
    session_id: UUID
    semantic_action: str = Field(min_length=1, max_length=160)
    capability: CapabilitySupport
    state: NativeSyncState
    backend: str = Field(default="dcs", min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=500)

    @property
    def synchronized(self) -> bool:
        return self.state in {NativeSyncState.SUCCEEDED, NativeSyncState.NOT_REQUIRED}


class AtcInterfacePolicy:
    """Defines the ORION-first pilot-facing ATC contract independent of procedure domain."""

    def __init__(self, mode: AtcIntegrationMode = AtcIntegrationMode.ORION_PRIMARY) -> None:
        self.mode = mode

    @property
    def pilot_uses_orion_as_primary_interface(self) -> bool:
        return self.mode is not AtcIntegrationMode.NATIVE_FALLBACK

    def native_action_required_for_pilot(self, result: NativeAtcSyncResult) -> bool:
        if self.mode is AtcIntegrationMode.NATIVE_FALLBACK:
            return True
        if result.synchronized:
            return False
        return self.mode is AtcIntegrationMode.ORION_WITH_NATIVE_FALLBACK

    def should_degrade_to_native(self, result: NativeAtcSyncResult) -> bool:
        return (
            self.mode is AtcIntegrationMode.ORION_PRIMARY
            and result.state in {NativeSyncState.FAILED, NativeSyncState.UNSUPPORTED}
        )
