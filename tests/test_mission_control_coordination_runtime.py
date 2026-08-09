from unittest.mock import patch

from orion.confirmations import ConfirmationStatus, ConfirmationStore
from orion.jtac_runtime import JtacDesignationMethod
from orion.mission import MissionSnapshot
from orion.mission_control_coordination import MissionControlAssignment, MissionControlCoordinationPlan
from orion.mission_control_coordination_runtime import MissionControlCoordinationRuntime
from orion.tactical_situation import TacticalThreatKind
from orion.voice_core import VoiceAgent


def _snapshot(mission_id: str = "mission-a") -> MissionSnapshot:
    return MissionSnapshot(mission_id=mission_id, units=[])


def _assignment(target: str, designator: str, *, sam: bool = False) -> MissionControlAssignment:
    return MissionControlAssignment(
        target_id=target,
        target_name=target.upper(),
        target_kind=TacticalThreatKind.SAM if sam else TacticalThreatKind.GROUND,
        tactical_priority=90,
        designator_id=designator,
        designator_name=designator.upper(),
        designation_method=JtacDesignationMethod.LASER,
        supports_laser=True,
    )


def _store_patches(store: ConfirmationStore):
    return (
        patch("orion.mission_control_coordination_runtime.confirmation_store", store),
        patch("orion.mission_control_autonomy_actions.confirmation_store", store),
    )


def test_creates_bounded_parallel_proposals_and_retains_stable_assignments() -> None:
    runtime = MissionControlCoordinationRuntime(max_active_proposals=2)
    runtime.enable()
    store = ConfirmationStore()
    plan = MissionControlCoordinationPlan(assignments=[_assignment("t1", "d1", sam=True), _assignment("t2", "d2"), _assignment("t3", "d3")])
    p1, p2 = _store_patches(store)
    with p1, p2, patch("orion.mission_control_coordination_runtime.build_mission_control_coordination_plan", return_value=plan), patch(
        "orion.mission_control_coordination_runtime.voice_commands.submit"
    ) as submit:
        first = runtime.observe(_snapshot())
        second = runtime.observe(_snapshot())
        status = runtime.status()
    assert len(first.created) == 2
    assert not second.created
    assert set(second.retained_action_ids) == {item.action_id for item in first.created}
    assert len(status.active_action_ids) == 2
    submit.assert_called_once()
    callout = submit.call_args.args[0]
    assert callout.agent is VoiceAgent.MISSION_CONTROL
    assert callout.context["created"] == 2


def test_replans_changed_designator_and_rejects_old_proposal() -> None:
    runtime = MissionControlCoordinationRuntime(max_active_proposals=2)
    runtime.enable()
    store = ConfirmationStore()
    first_plan = MissionControlCoordinationPlan(assignments=[_assignment("t1", "d1")])
    second_plan = MissionControlCoordinationPlan(assignments=[_assignment("t1", "d2")])
    p1, p2 = _store_patches(store)
    with p1, p2:
        with patch("orion.mission_control_coordination_runtime.build_mission_control_coordination_plan", return_value=first_plan):
            first = runtime.observe(_snapshot())
        old = first.created[0]
        with patch("orion.mission_control_coordination_runtime.build_mission_control_coordination_plan", return_value=second_plan):
            second = runtime.observe(_snapshot())
        assert second.cancelled_action_ids == [old.action_id]
        assert store.get(old.action_id).status is ConfirmationStatus.REJECTED
        assert second.created[0].payload["designator_id"] == "d2"


def test_mission_change_rejects_old_actions() -> None:
    runtime = MissionControlCoordinationRuntime()
    runtime.enable()
    store = ConfirmationStore()
    plan = MissionControlCoordinationPlan(assignments=[_assignment("t1", "d1")])
    p1, p2 = _store_patches(store)
    with p1, p2, patch("orion.mission_control_coordination_runtime.build_mission_control_coordination_plan", return_value=plan):
        first = runtime.observe(_snapshot("mission-a"))
        runtime.observe(_snapshot("mission-b"))
        assert store.get(first.created[0].action_id).status is ConfirmationStatus.REJECTED
        assert runtime.status().mission_id == "mission-b"


def test_disable_rejects_all_parallel_pending_actions() -> None:
    runtime = MissionControlCoordinationRuntime()
    runtime.enable()
    store = ConfirmationStore()
    plan = MissionControlCoordinationPlan(assignments=[_assignment("t1", "d1"), _assignment("t2", "d2")])
    p1, p2 = _store_patches(store)
    with p1, p2, patch("orion.mission_control_coordination_runtime.build_mission_control_coordination_plan", return_value=plan):
        result = runtime.observe(_snapshot())
        runtime.disable()
        assert all(store.get(item.action_id).status is ConfirmationStatus.REJECTED for item in result.created)
        assert runtime.status().active_action_ids == []
