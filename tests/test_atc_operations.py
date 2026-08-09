from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import (
    AcknowledgementState,
    CapabilitySupport,
    CapabilityValue,
    CommitmentState,
    FreshnessClass,
    InstructionState,
    OperationalInstruction,
    OperationalOverlay,
    SequencedTrafficEntry,
    TrafficPriority,
    VoicePriority,
)


def test_instruction_transmission_does_not_acknowledge() -> None:
    instruction = OperationalInstruction(
        session_id=uuid4(),
        issuing_agency=ControllerAgency.CARRIER_MARSHAL,
        authority_scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        semantic_action="contact_approach",
    )

    instruction.mark_transmitted()

    assert instruction.state is InstructionState.TRANSMITTED
    assert instruction.acknowledgement_state is AcknowledgementState.PENDING


def test_instruction_acknowledgement_is_explicit() -> None:
    instruction = OperationalInstruction(
        session_id=uuid4(),
        issuing_agency=ControllerAgency.AIRPORT_TOWER,
        authority_scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        semantic_action="hold_position",
    )

    instruction.mark_transmitted()
    instruction.acknowledge()

    assert instruction.state is InstructionState.ACKNOWLEDGED
    assert instruction.acknowledgement_state is AcknowledgementState.ACKNOWLEDGED


def test_instruction_retry_is_bounded() -> None:
    instruction = OperationalInstruction(
        session_id=uuid4(),
        issuing_agency=ControllerAgency.CARRIER_APPROACH,
        authority_scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        semantic_action="descend",
        max_retries=1,
    )

    instruction.mark_transmitted()
    instruction.retry()
    with pytest.raises(ValueError, match="retry limit"):
        instruction.retry()


def test_instruction_expires_without_acknowledgement() -> None:
    now = datetime.now(UTC)
    instruction = OperationalInstruction(
        session_id=uuid4(),
        issuing_agency=ControllerAgency.CARRIER_TOWER,
        authority_scope=ControllerAuthorityScope.LANDING_AREA,
        semantic_action="landing_area_status",
        expires_at=now + timedelta(seconds=5),
    )

    assert not instruction.expire_if_due(now + timedelta(seconds=4))
    assert instruction.expire_if_due(now + timedelta(seconds=6))
    assert instruction.state is InstructionState.EXPIRED
    assert instruction.acknowledgement_state is AcknowledgementState.EXPIRED


def test_unknown_or_stale_capability_is_not_positive_assertion() -> None:
    unknown = CapabilityValue(support=CapabilitySupport.UNKNOWN)
    stale = CapabilityValue(
        support=CapabilitySupport.SUPPORTED,
        value=True,
        freshness=FreshnessClass.STALE,
    )
    fresh = CapabilityValue(
        support=CapabilitySupport.SUPPORTED,
        value=True,
        freshness=FreshnessClass.FRESH,
    )

    assert not unknown.usable_for_positive_assertion
    assert not stale.usable_for_positive_assertion
    assert fresh.usable_for_positive_assertion


def test_commitment_and_priority_are_independent_dimensions() -> None:
    entry = SequencedTrafficEntry(
        session_id=uuid4(),
        priority=TrafficPriority.EMERGENCY,
        commitment=CommitmentState.RESERVED,
        sequence_index=0,
        reason="declared emergency",
    )

    assert entry.priority is TrafficPriority.EMERGENCY
    assert entry.commitment is CommitmentState.RESERVED
    assert TrafficPriority.EMERGENCY > TrafficPriority.COMMITTED_TRAFFIC
    assert CommitmentState.IRREVERSIBLE > CommitmentState.PHYSICALLY_COMMITTED


def test_operational_overlay_does_not_replace_procedural_state() -> None:
    procedural_state = "eat_wait"
    overlays = {OperationalOverlay.LOST_COMMS_SUSPECTED, OperationalOverlay.CRITICAL_FUEL}

    assert procedural_state == "eat_wait"
    assert OperationalOverlay.LOST_COMMS_SUSPECTED in overlays
    assert OperationalOverlay.CRITICAL_FUEL in overlays


def test_voice_priority_order_keeps_safety_above_conversation() -> None:
    assert VoicePriority.IMMEDIATE_SAFETY > VoicePriority.EMERGENCY
    assert VoicePriority.EMERGENCY > VoicePriority.PROCEDURAL
    assert VoicePriority.PROCEDURAL > VoicePriority.FREE_FORM
