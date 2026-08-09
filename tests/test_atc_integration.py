from uuid import uuid4

from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_integration import AtcIntegratedRuntime
from orion.atc_operations import (
    CommitmentState,
    OperationalInstruction,
    OperationalOverlay,
    TrafficConflict,
    TrafficPriority,
)
from orion.atc_session_state import ConflictResolutionAction


def test_integrated_runtime_preserves_procedural_state_with_overlay() -> None:
    runtime = AtcIntegratedRuntime()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="cvn")
    runtime.open_session(identity, procedural_state="eat_wait")

    updated = runtime.add_overlay(
        identity.session_id,
        OperationalOverlay.CRITICAL_FUEL,
        reason="pilot reported critical fuel",
    )

    assert updated.procedural_state == "eat_wait"
    assert OperationalOverlay.CRITICAL_FUEL in updated.overlays
    events = runtime.core.history.list(identity.session_id)
    assert events[-1].event_type == "operational_overlay_added"
    assert events[-1].details["procedural_state"] == "eat_wait"


def test_integrated_instruction_requires_scoped_authority() -> None:
    runtime = AtcIntegratedRuntime()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1")
    runtime.open_session(identity, procedural_state="holding")
    runtime.claim_authority(
        session_id=identity.session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.CARRIER_MARSHAL,
        reason="marshal owns inbound traffic",
    )

    instruction = runtime.issue_instruction(
        OperationalInstruction(
            session_id=identity.session_id,
            issuing_agency=ControllerAgency.CARRIER_MARSHAL,
            authority_scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
            semantic_action="commence",
        )
    )

    assert instruction.state.value == "transmitted"
    acknowledged = runtime.acknowledge_instruction(instruction.instruction_id)
    assert acknowledged.state.value == "acknowledged"
    event_types = [event.event_type for event in runtime.core.history.list(identity.session_id)]
    assert "instruction_created" in event_types
    assert "instruction_transmitted" in event_types
    assert "instruction_acknowledged" in event_types


def test_integrated_sequence_uses_runtime_priority_and_commitment() -> None:
    runtime = AtcIntegratedRuntime()
    normal = AtcSessionIdentity(mission_id="m1", aircraft_id="normal")
    emergency = AtcSessionIdentity(mission_id="m1", aircraft_id="emergency")
    runtime.open_session(normal, procedural_state="holding")
    runtime.open_session(emergency, procedural_state="holding")
    runtime.set_commitment(
        normal.session_id,
        CommitmentState.RESERVED,
        reason="existing slot",
    )
    runtime.set_priority(
        emergency.session_id,
        TrafficPriority.EMERGENCY,
        reason="declared emergency",
    )

    ordered = runtime.sequence([normal.session_id, emergency.session_id])

    assert ordered[0].session_id == emergency.session_id
    assert runtime.core.history.list(emergency.session_id)[-1].event_type == "traffic_sequence_evaluated"


def test_integrated_conflict_protects_irreversible_traffic() -> None:
    runtime = AtcIntegratedRuntime()
    committed = AtcSessionIdentity(mission_id="m1", aircraft_id="catapult")
    emergency = AtcSessionIdentity(mission_id="m1", aircraft_id="inbound")
    runtime.open_session(committed, procedural_state="catapult_stroke")
    runtime.open_session(emergency, procedural_state="final")
    runtime.set_commitment(
        committed.session_id,
        CommitmentState.IRREVERSIBLE,
        reason="catapult stroke started",
    )
    runtime.set_priority(
        emergency.session_id,
        TrafficPriority.EMERGENCY,
        reason="declared emergency",
    )

    conflict = TrafficConflict(
        class_name="launch_recovery_interaction",
        sessions=[committed.session_id, emergency.session_id],
        reason="shared carrier operating area",
    )
    action, reason = runtime.resolve_conflict(conflict)

    assert action == ConflictResolutionAction.PROTECT_COMMITTED
    assert "irreversible" in reason
    for session_id in conflict.sessions:
        event_types = [event.event_type for event in runtime.core.history.list(session_id)]
        assert "traffic_conflict_detected" in event_types
        assert "traffic_conflict_resolved" in event_types


def test_integrated_runtime_rejects_unknown_session() -> None:
    runtime = AtcIntegratedRuntime()
    missing = uuid4()

    try:
        runtime.transition(missing, "final", reason="test")
    except KeyError as exc:
        assert "runtime session" in str(exc)
    else:
        raise AssertionError("missing session must be rejected")
