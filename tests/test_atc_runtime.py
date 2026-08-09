from uuid import uuid4

import pytest

from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import (
    CommitmentState,
    OperationalInstruction,
    ResourceAssignment,
    TrafficConflict,
    TrafficPriority,
)
from orion.atc_runtime import AtcCoordinationRegistry, AtcCoreFlow, AtcEventHistory


def test_event_history_preserves_reasoned_order() -> None:
    history = AtcEventHistory()
    session_id = uuid4()

    history.record(session_id=session_id, event_type="one", reason="first reason")
    history.record(session_id=session_id, event_type="two", reason="second reason")

    events = history.list(session_id)
    assert [event.event_type for event in events] == ["one", "two"]
    assert [event.reason for event in events] == ["first reason", "second reason"]


def test_resource_assignment_is_exclusive_across_sessions() -> None:
    registry = AtcCoordinationRegistry()
    first = ResourceAssignment(
        session_id=uuid4(),
        resource_type="runway",
        resource_id="09",
        reason="departure slot",
    )
    registry.assign_resource(first)

    with pytest.raises(ValueError, match="already assigned"):
        registry.assign_resource(
            ResourceAssignment(
                session_id=uuid4(),
                resource_type="runway",
                resource_id="09",
                reason="conflicting arrival",
            )
        )


def test_conflict_is_visible_to_all_involved_sessions() -> None:
    registry = AtcCoordinationRegistry()
    first = uuid4()
    second = uuid4()
    conflict = TrafficConflict(
        class_name="insufficient_interval",
        sessions=[first, second],
        reason="minimum interval not met",
    )

    registry.record_conflict(conflict)

    assert registry.list_conflicts(first)[0].conflict_id == conflict.conflict_id
    assert registry.list_conflicts(second)[0].conflict_id == conflict.conflict_id


def test_core_flow_rejects_instruction_outside_authority_scope() -> None:
    flow = AtcCoreFlow()
    session = flow.open_session(
        AtcSessionIdentity(mission_id="mission-a", aircraft_id="springfield-1-1")
    )
    flow.claim_authority(
        session_id=session.session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.AIRPORT_TOWER,
        reason="tower owns traffic",
    )

    with pytest.raises(ValueError, match="does not own"):
        flow.issue_instruction(
            OperationalInstruction(
                session_id=session.session_id,
                issuing_agency=ControllerAgency.MISSION_CONTROL,
                authority_scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
                semantic_action="climb",
            )
        )


def test_end_to_end_instruction_and_handoff_history() -> None:
    flow = AtcCoreFlow()
    session = flow.open_session(
        AtcSessionIdentity(mission_id="mission-b", aircraft_id="colt-2-1", facility_id="cvn-71")
    )
    flow.claim_authority(
        session_id=session.session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.CARRIER_MARSHAL,
        reason="checked in with marshal",
    )

    instruction = flow.issue_instruction(
        OperationalInstruction(
            session_id=session.session_id,
            issuing_agency=ControllerAgency.CARRIER_MARSHAL,
            authority_scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
            semantic_action="contact_approach",
        )
    )
    flow.instructions.transmit(instruction.instruction_id)
    flow.instructions.acknowledge(instruction.instruction_id)

    handoff_id = flow.acknowledgement_handoff(
        session_id=session.session_id,
        source=ControllerAgency.CARRIER_MARSHAL,
        destination=ControllerAgency.CARRIER_APPROACH,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        reason="approach handoff",
    )
    flow.complete_acknowledged_handoff(handoff_id)

    owner = flow.authority.get_owner(session.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None
    assert owner.agency is ControllerAgency.CARRIER_APPROACH

    event_types = [event.event_type for event in flow.history.list(session.session_id)]
    assert event_types == [
        "session_opened",
        "authority_claimed",
        "instruction_created",
        "instruction_transmitted",
        "instruction_acknowledged",
        "handoff_started",
        "handoff_completed",
    ]


def test_priority_and_commitment_protection_is_deterministic() -> None:
    assert AtcCoreFlow.should_protect(TrafficPriority.EMERGENCY, CommitmentState.UNCOMMITTED)
    assert AtcCoreFlow.should_protect(
        TrafficPriority.NORMAL,
        CommitmentState.PHYSICALLY_COMMITTED,
    )
    assert not AtcCoreFlow.should_protect(TrafficPriority.NORMAL, CommitmentState.RESERVED)
