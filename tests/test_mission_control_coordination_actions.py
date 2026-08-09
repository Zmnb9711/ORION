from unittest.mock import patch

from orion.confirmations import ConfirmationStatus, ConfirmationStore
from orion.jtac_runtime import JtacDesignationMethod
from orion.mission import MissionSnapshot
from orion.mission_control_coordination import MissionControlAssignment, MissionControlCoordinationPlan
from orion.mission_control_coordination_actions import (
    create_coordination_pending_action,
    resolve_coordination_pending_action,
)
from orion.mission_control_jtac import MissionControlJtacResult
from orion.tactical_situation import TacticalThreatKind


def _assignment(
    *,
    target_id: str = "sam-1",
    designator_id: str = "jtac-1",
    method: JtacDesignationMethod = JtacDesignationMethod.LASER,
) -> MissionControlAssignment:
    return MissionControlAssignment(
        target_id=target_id,
        target_name=target_id.upper(),
        target_kind=TacticalThreatKind.SAM,
        tactical_priority=95,
        designator_id=designator_id,
        designator_name=designator_id.upper(),
        designation_method=method,
        supports_laser=method is JtacDesignationMethod.LASER,
        supports_smoke=True,
    )


def test_confirmed_coordination_assignment_executes_exact_asset_and_method() -> None:
    store = ConfirmationStore()
    assignment = _assignment()
    snapshot = MissionSnapshot(mission_id="mission-1")
    with patch("orion.mission_control_coordination_actions.confirmation_store", store), patch(
        "orion.mission_control_coordination_actions.mission_store.get", return_value=snapshot
    ), patch(
        "orion.mission_control_coordination_actions.build_mission_control_coordination_plan",
        return_value=MissionControlCoordinationPlan(assignments=[assignment], available_designators=1),
    ), patch(
        "orion.mission_control_coordination_actions.orchestrate_jtac",
        return_value=MissionControlJtacResult(accepted=True, target_id="sam-1", spoken_text="queued"),
    ) as orchestrate:
        pending = create_coordination_pending_action(assignment)
        result = resolve_coordination_pending_action(pending.action_id, confirm=True, language="ru")

    assert result.stale is False
    assert result.executed is True
    assert result.pending_action.status is ConfirmationStatus.CONFIRMED
    request = orchestrate.call_args.args[0]
    assert request.target_id == "sam-1"
    assert request.requested_asset_id == "jtac-1"
    assert request.method is JtacDesignationMethod.LASER
    assert request.laser_code == 1688
    assert request.language == "ru"


def test_changed_coordination_assignment_is_rejected_as_stale() -> None:
    store = ConfirmationStore()
    original = _assignment(designator_id="jtac-1")
    replacement = _assignment(designator_id="jtac-2")
    snapshot = MissionSnapshot(mission_id="mission-1")
    with patch("orion.mission_control_coordination_actions.confirmation_store", store), patch(
        "orion.mission_control_coordination_actions.mission_store.get", return_value=snapshot
    ), patch(
        "orion.mission_control_coordination_actions.build_mission_control_coordination_plan",
        return_value=MissionControlCoordinationPlan(assignments=[replacement], available_designators=1),
    ), patch("orion.mission_control_coordination_actions.orchestrate_jtac") as orchestrate:
        pending = create_coordination_pending_action(original)
        result = resolve_coordination_pending_action(pending.action_id, confirm=True)

    assert result.stale is True
    assert result.executed is False
    assert result.pending_action.status is ConfirmationStatus.REJECTED
    orchestrate.assert_not_called()


def test_mission_boundary_invalidates_coordination_assignment() -> None:
    store = ConfirmationStore()
    assignment = _assignment()
    snapshots = [MissionSnapshot(mission_id="mission-1"), MissionSnapshot(mission_id="mission-2")]
    with patch("orion.mission_control_coordination_actions.confirmation_store", store), patch(
        "orion.mission_control_coordination_actions.mission_store.get", side_effect=snapshots
    ), patch("orion.mission_control_coordination_actions.orchestrate_jtac") as orchestrate:
        pending = create_coordination_pending_action(assignment)
        result = resolve_coordination_pending_action(pending.action_id, confirm=True)

    assert result.stale is True
    assert result.pending_action.status is ConfirmationStatus.REJECTED
    orchestrate.assert_not_called()


def test_rejected_coordination_assignment_does_not_execute() -> None:
    store = ConfirmationStore()
    assignment = _assignment()
    snapshot = MissionSnapshot(mission_id="mission-1")
    with patch("orion.mission_control_coordination_actions.confirmation_store", store), patch(
        "orion.mission_control_coordination_actions.mission_store.get", return_value=snapshot
    ), patch("orion.mission_control_coordination_actions.orchestrate_jtac") as orchestrate:
        pending = create_coordination_pending_action(assignment)
        result = resolve_coordination_pending_action(pending.action_id, confirm=False)

    assert result.pending_action.status is ConfirmationStatus.REJECTED
    assert result.executed is False
    orchestrate.assert_not_called()
