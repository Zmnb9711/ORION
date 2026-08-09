from orion.atc_core import AtcSessionIdentity
from orion.atc_integration import AtcIntegratedRuntime
from orion.atc_operations import CapabilitySupport, OperationalOverlay
from orion.atc_simulator_sync import AtcIntegrationMode, NativeSyncState


def test_native_sync_failure_degrades_without_losing_procedural_state() -> None:
    runtime = AtcIntegratedRuntime()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="airfield")
    runtime.open_session(identity, procedural_state="approach")

    request = runtime.request_native_sync(
        session_id=identity.session_id,
        semantic_action="request_landing",
        adapter_kind="airport",
        capability=CapabilitySupport.SUPPORTED,
        reason="mirror landing request into DCS",
    )
    runtime.resolve_native_sync(
        request.request_id,
        state=NativeSyncState.FAILED,
        reason="native DCS action failed",
    )

    session = runtime.sessions.get(identity.session_id)
    assert session is not None
    assert session.procedural_state == "approach"
    assert OperationalOverlay.SIMULATOR_SYNC_DEGRADED in session.overlays
    assert runtime.get_integration_mode(identity.session_id) is AtcIntegrationMode.ORION_WITH_NATIVE_FALLBACK


def test_unsupported_native_sync_enters_compatibility_fallback_mode() -> None:
    runtime = AtcIntegratedRuntime()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="cvn")
    runtime.open_session(identity, procedural_state="marshal")

    request = runtime.request_native_sync(
        session_id=identity.session_id,
        semantic_action="commence",
        adapter_kind="carrier",
        capability=CapabilitySupport.UNKNOWN,
        reason="try native carrier commence synchronization",
    )
    resolved = runtime.resolve_native_sync(
        request.request_id,
        state=NativeSyncState.UNSUPPORTED,
        capability=CapabilitySupport.UNSUPPORTED,
        reason="DCS adapter cannot automate this transition",
    )

    assert resolved.capability is CapabilitySupport.UNSUPPORTED
    assert runtime.get_integration_mode(identity.session_id) is AtcIntegrationMode.ORION_WITH_NATIVE_FALLBACK


def test_explicit_native_fallback_preserves_session() -> None:
    runtime = AtcIntegratedRuntime()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1")
    runtime.open_session(identity, procedural_state="final")

    mode = runtime.require_native_fallback(
        identity.session_id,
        reason="required DCS synchronization cannot be automated safely",
    )

    session = runtime.sessions.get(identity.session_id)
    assert session is not None
    assert session.procedural_state == "final"
    assert mode is AtcIntegrationMode.NATIVE_FALLBACK
    assert OperationalOverlay.SIMULATOR_SYNC_DEGRADED in session.overlays


def test_confirmed_sync_can_clear_degraded_overlay_without_advancing_procedure() -> None:
    runtime = AtcIntegratedRuntime()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1")
    runtime.open_session(identity, procedural_state="hold_short")
    runtime.require_native_fallback(identity.session_id, reason="temporary sync loss")

    request = runtime.request_native_sync(
        session_id=identity.session_id,
        semantic_action="ready_for_departure",
        adapter_kind="airport",
        capability=CapabilitySupport.SUPPORTED,
        reason="retry native departure synchronization",
    )
    runtime.resolve_native_sync(
        request.request_id,
        state=NativeSyncState.CONFIRMED,
        capability=CapabilitySupport.SUPPORTED,
        reason="native DCS synchronization confirmed",
    )

    session = runtime.sessions.get(identity.session_id)
    assert session is not None
    assert session.procedural_state == "hold_short"
    assert OperationalOverlay.SIMULATOR_SYNC_DEGRADED not in session.overlays
    assert runtime.get_integration_mode(identity.session_id) is AtcIntegrationMode.NATIVE_FALLBACK


def test_restore_orion_primary_is_explicit() -> None:
    runtime = AtcIntegratedRuntime()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1")
    runtime.open_session(identity, procedural_state="taxi")
    runtime.require_native_fallback(identity.session_id, reason="adapter degraded")

    mode = runtime.restore_orion_primary(identity.session_id, reason="adapter health restored")

    session = runtime.sessions.get(identity.session_id)
    assert session is not None
    assert mode is AtcIntegrationMode.ORION_PRIMARY
    assert session.procedural_state == "taxi"
    assert OperationalOverlay.SIMULATOR_SYNC_DEGRADED not in session.overlays


def test_native_sync_audit_trail_records_request_resolution_and_mode_change() -> None:
    runtime = AtcIntegratedRuntime()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1")
    runtime.open_session(identity, procedural_state="inbound")

    request = runtime.request_native_sync(
        session_id=identity.session_id,
        semantic_action="inbound",
        adapter_kind="carrier",
        capability=CapabilitySupport.SUPPORTED,
        reason="mirror inbound call",
    )
    runtime.resolve_native_sync(
        request.request_id,
        state=NativeSyncState.FAILED,
        reason="native inbound synchronization failed",
    )

    events = runtime.core.history.list(identity.session_id)
    event_types = [event.event_type for event in events]
    assert "native_sync_requested" in event_types
    assert "native_sync_resolved" in event_types
    assert "integration_mode_changed" in event_types
    assert "simulator_sync_degraded" in event_types
