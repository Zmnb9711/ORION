from uuid import uuid4

from orion.atc_interface import (
    AtcIntegrationMode,
    AtcInterfacePolicy,
    NativeAtcSyncResult,
    NativeSyncState,
)
from orion.atc_operations import CapabilitySupport


def _result(state: NativeSyncState, capability: CapabilitySupport) -> NativeAtcSyncResult:
    return NativeAtcSyncResult(
        session_id=uuid4(),
        semantic_action="request_taxi",
        capability=capability,
        state=state,
        reason="test",
    )


def test_orion_primary_is_pilot_facing_default() -> None:
    policy = AtcInterfacePolicy()

    assert policy.mode is AtcIntegrationMode.ORION_PRIMARY
    assert policy.pilot_uses_orion_as_primary_interface


def test_successful_native_sync_is_invisible_to_pilot() -> None:
    policy = AtcInterfacePolicy(AtcIntegrationMode.ORION_PRIMARY)
    result = _result(NativeSyncState.SUCCEEDED, CapabilitySupport.SUPPORTED)

    assert not policy.native_action_required_for_pilot(result)
    assert not policy.should_degrade_to_native(result)


def test_primary_mode_degrades_when_native_sync_is_unsupported() -> None:
    policy = AtcInterfacePolicy(AtcIntegrationMode.ORION_PRIMARY)
    result = _result(NativeSyncState.UNSUPPORTED, CapabilitySupport.UNSUPPORTED)

    assert policy.should_degrade_to_native(result)
    assert not policy.native_action_required_for_pilot(result)


def test_compatibility_mode_requests_native_action_only_when_needed() -> None:
    policy = AtcInterfacePolicy(AtcIntegrationMode.ORION_WITH_NATIVE_FALLBACK)
    failed = _result(NativeSyncState.FAILED, CapabilitySupport.SUPPORTED)
    succeeded = _result(NativeSyncState.SUCCEEDED, CapabilitySupport.SUPPORTED)

    assert policy.native_action_required_for_pilot(failed)
    assert not policy.native_action_required_for_pilot(succeeded)


def test_native_fallback_is_not_orion_primary() -> None:
    policy = AtcInterfacePolicy(AtcIntegrationMode.NATIVE_FALLBACK)
    result = _result(NativeSyncState.NOT_REQUIRED, CapabilitySupport.UNKNOWN)

    assert not policy.pilot_uses_orion_as_primary_interface
    assert policy.native_action_required_for_pilot(result)
