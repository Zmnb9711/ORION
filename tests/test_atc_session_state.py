from uuid import uuid4

import pytest

from orion.atc_core import AtcSessionIdentity
from orion.atc_operations import (
    CommitmentState,
    OperationalOverlay,
    SequencedTrafficEntry,
    TrafficConflict,
    TrafficPriority,
)
from orion.atc_session_state import (
    AtcRuntimeSession,
    AtcSessionRuntimeStore,
    ConflictResolutionAction,
    GenericConflictResolutionPolicy,
    GenericSequencingPolicy,
)


def _entry(
    *,
    priority: TrafficPriority,
    commitment: CommitmentState,
    sequence_index: int,
) -> SequencedTrafficEntry:
    return SequencedTrafficEntry(
        session_id=uuid4(),
        priority=priority,
        commitment=commitment,
        sequence_index=sequence_index,
        reason="test",
    )


def test_overlay_preserves_procedural_state() -> None:
    session = AtcRuntimeSession(
        identity=AtcSessionIdentity(mission_id="m1", aircraft_id="a1"),
        procedural_state="eat_wait",
    )

    session.add_overlay(OperationalOverlay.CRITICAL_FUEL, reason="pilot fuel report")

    assert session.procedural_state == "eat_wait"
    assert OperationalOverlay.CRITICAL_FUEL in session.overlays


def test_runtime_store_returns_isolated_copies() -> None:
    store = AtcSessionRuntimeStore()
    session = AtcRuntimeSession(
        identity=AtcSessionIdentity(mission_id="m1", aircraft_id="a1"),
        procedural_state="holding",
    )
    store.create(session)

    loaded = store.get(session.identity.session_id)
    assert loaded is not None
    loaded.transition("commencing", reason="released")

    original = store.get(session.identity.session_id)
    assert original is not None
    assert original.procedural_state == "holding"


def test_commitment_cannot_be_reduced_implicitly() -> None:
    session = AtcRuntimeSession(
        identity=AtcSessionIdentity(mission_id="m1", aircraft_id="a1"),
        procedural_state="final",
        commitment=CommitmentState.PHYSICALLY_COMMITTED,
    )

    with pytest.raises(ValueError, match="cannot be reduced"):
        session.set_commitment(CommitmentState.RESERVED, reason="invalid rollback")


def test_sequencing_orders_priority_then_commitment_then_sequence() -> None:
    normal = _entry(
        priority=TrafficPriority.NORMAL,
        commitment=CommitmentState.UNCOMMITTED,
        sequence_index=0,
    )
    emergency = _entry(
        priority=TrafficPriority.EMERGENCY,
        commitment=CommitmentState.RESERVED,
        sequence_index=8,
    )
    committed = _entry(
        priority=TrafficPriority.NORMAL,
        commitment=CommitmentState.PHYSICALLY_COMMITTED,
        sequence_index=3,
    )

    ordered = GenericSequencingPolicy().order([normal, committed, emergency])

    assert [item.session_id for item in ordered] == [
        emergency.session_id,
        committed.session_id,
        normal.session_id,
    ]


def test_irreversible_incumbent_cannot_be_displaced() -> None:
    incumbent = _entry(
        priority=TrafficPriority.NORMAL,
        commitment=CommitmentState.IRREVERSIBLE,
        sequence_index=0,
    )
    emergency = _entry(
        priority=TrafficPriority.EMERGENCY,
        commitment=CommitmentState.IRREVERSIBLE,
        sequence_index=1,
    )

    assert not GenericSequencingPolicy().may_displace(
        candidate=emergency,
        incumbent=incumbent,
    )


def test_conflict_policy_protects_physically_committed_traffic() -> None:
    committed = _entry(
        priority=TrafficPriority.NORMAL,
        commitment=CommitmentState.PHYSICALLY_COMMITTED,
        sequence_index=0,
    )
    other = _entry(
        priority=TrafficPriority.EMERGENCY,
        commitment=CommitmentState.UNCOMMITTED,
        sequence_index=1,
    )
    conflict = TrafficConflict(
        class_name="final_conflict",
        sessions=[committed.session_id, other.session_id],
        reason="paths conflict",
    )

    action, reason = GenericConflictResolutionPolicy().resolve(
        conflict,
        {committed.session_id: committed, other.session_id: other},
    )

    assert action == ConflictResolutionAction.PROTECT_COMMITTED
    assert "committed" in reason


def test_conflict_policy_resequences_uncommitted_priority_difference() -> None:
    normal = _entry(
        priority=TrafficPriority.NORMAL,
        commitment=CommitmentState.UNCOMMITTED,
        sequence_index=0,
    )
    emergency = _entry(
        priority=TrafficPriority.EMERGENCY,
        commitment=CommitmentState.UNCOMMITTED,
        sequence_index=1,
    )
    conflict = TrafficConflict(
        class_name="sequence_conflict",
        sessions=[normal.session_id, emergency.session_id],
        reason="same protected slot",
    )

    action, _ = GenericConflictResolutionPolicy().resolve(
        conflict,
        {normal.session_id: normal, emergency.session_id: emergency},
    )

    assert action == ConflictResolutionAction.RESEQUENCE


def test_unknown_conflict_state_suspends_new_clearances() -> None:
    conflict = TrafficConflict(
        class_name="unknown_conflict",
        sessions=[uuid4()],
        reason="missing session state",
    )

    action, _ = GenericConflictResolutionPolicy().resolve(conflict, {})

    assert action == ConflictResolutionAction.SUSPEND_NEW_CLEARANCES
