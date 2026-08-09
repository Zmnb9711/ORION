from uuid import uuid4

import pytest

from orion.atc_operations import CapabilitySupport
from orion.atc_simulator_sync import (
    AtcIntegrationMode,
    AtcSimulatorSyncRegistry,
    NativeActionRequest,
    NativeSyncState,
)


def test_orion_primary_is_explicit_default_target_mode() -> None:
    assert AtcIntegrationMode.ORION_PRIMARY.value == "orion_primary"


def test_native_sync_request_lifecycle_is_explicit() -> None:
    registry = AtcSimulatorSyncRegistry()
    session_id = uuid4()
    request = registry.create(
        NativeActionRequest(
            session_id=session_id,
            semantic_action="request_landing",
            adapter_kind="airport",
            capability=CapabilitySupport.SUPPORTED,
            reason="mirror ORION landing request into DCS",
        )
    )

    assert request.state is NativeSyncState.PENDING
    resolved = registry.resolve(
        request.request_id,
        state=NativeSyncState.CONFIRMED,
        capability=CapabilitySupport.SUPPORTED,
        reason="DCS synchronization confirmed",
    )
    assert resolved.state is NativeSyncState.CONFIRMED
    assert resolved.completed_at is not None


def test_unsupported_sync_is_not_reported_as_confirmed() -> None:
    registry = AtcSimulatorSyncRegistry()
    request = registry.create(
        NativeActionRequest(
            session_id=uuid4(),
            semantic_action="ball_call",
            adapter_kind="carrier",
            capability=CapabilitySupport.UNKNOWN,
            reason="attempt carrier native synchronization",
        )
    )

    resolved = registry.resolve(
        request.request_id,
        state=NativeSyncState.UNSUPPORTED,
        capability=CapabilitySupport.UNSUPPORTED,
        reason="module does not expose native synchronization",
    )

    assert resolved.state is NativeSyncState.UNSUPPORTED
    assert resolved.capability is CapabilitySupport.UNSUPPORTED


def test_resolved_sync_request_cannot_be_rewritten() -> None:
    registry = AtcSimulatorSyncRegistry()
    request = registry.create(
        NativeActionRequest(
            session_id=uuid4(),
            semantic_action="inbound",
            adapter_kind="airport",
            reason="native ATC synchronization",
        )
    )
    registry.resolve(
        request.request_id,
        state=NativeSyncState.FAILED,
        reason="adapter failure",
    )

    with pytest.raises(ValueError, match="already final"):
        registry.resolve(
            request.request_id,
            state=NativeSyncState.CONFIRMED,
            reason="late rewrite",
        )


def test_registry_is_session_scoped() -> None:
    registry = AtcSimulatorSyncRegistry()
    first = uuid4()
    second = uuid4()
    registry.create(
        NativeActionRequest(
            session_id=first,
            semantic_action="request_taxi",
            adapter_kind="airport",
            reason="first",
        )
    )
    registry.create(
        NativeActionRequest(
            session_id=second,
            semantic_action="commence",
            adapter_kind="carrier",
            reason="second",
        )
    )

    assert len(registry.list_session(first)) == 1
    assert len(registry.list_session(second)) == 1
    registry.clear_session(first)
    assert registry.list_session(first) == []
    assert len(registry.list_session(second)) == 1
