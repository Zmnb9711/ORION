from unittest.mock import patch

from orion.confirmations import ConfirmationStatus, ConfirmationStore
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_control_autonomy import MissionControlAction, MissionControlAutonomyDecision
from orion.mission_control_autonomy_actions import create_autonomy_pending_action, resolve_autonomy_pending_action
from orion.mission_control_jtac import MissionControlJtacResult


def _decision(action: MissionControlAction) -> MissionControlAutonomyDecision:
    return MissionControlAutonomyDecision(
        action=action,
        target_id="target-1",
        target_name="SA-11",
        confidence=0.9,
        reason="test",
        requires_pilot_confirmation=True,
        available_designators=1,
    )


def _snapshot(*, mission_id: str = "mission-1", alive: bool = True, detected: bool = True) -> MissionSnapshot:
    return MissionSnapshot(
        mission_id=mission_id,
        units=[
            MissionUnit(
                unit_id="target-1",
                name="SA-11",
                coalition=Coalition.RED,
                category=UnitCategory.GROUND,
                type_name="Buk SR 9S18M1",
                position=MissionPosition(latitude=41.1234567, longitude=41.7654321, altitude_m=300),
                alive=alive,
                detected=detected,
            )
        ],
    )


def test_rejected_proposal_has_no_side_effect() -> None:
    store = ConfirmationStore()
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.orchestrate_jtac"
    ) as orchestrate:
        pending = create_autonomy_pending_action(_decision(MissionControlAction.SUGGEST_JTAC))
        result = resolve_autonomy_pending_action(pending.action_id, confirm=False)
    assert result.pending_action.status is ConfirmationStatus.REJECTED
    assert result.executed is False
    orchestrate.assert_not_called()


def test_confirmed_jtac_proposal_executes_orchestration() -> None:
    store = ConfirmationStore()
    snapshot = _snapshot()
    decision = _decision(MissionControlAction.SUGGEST_JTAC)
    jtac_result = MissionControlJtacResult(accepted=True, target_id="target-1", spoken_text="JTAC assigned")
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", return_value=snapshot
    ), patch("orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=decision), patch(
        "orion.mission_control_autonomy_actions.orchestrate_jtac", return_value=jtac_result
    ) as orchestrate:
        pending = create_autonomy_pending_action(decision)
        result = resolve_autonomy_pending_action(pending.action_id, confirm=True)
    assert result.pending_action.status is ConfirmationStatus.CONFIRMED
    assert result.executed is True
    assert result.jtac_result == jtac_result
    assert orchestrate.call_args.args[0].target_id == "target-1"


def test_confirmed_9line_proposal_builds_grounded_seed() -> None:
    store = ConfirmationStore()
    snapshot = _snapshot()
    decision = _decision(MissionControlAction.SUGGEST_9LINE)
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", return_value=snapshot
    ), patch("orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=decision):
        pending = create_autonomy_pending_action(decision)
        result = resolve_autonomy_pending_action(pending.action_id, confirm=True)
    assert result.executed is True
    assert result.cas_9line_seed is not None
    assert result.cas_9line_seed.target_location == "41.123457, 41.765432"
    assert result.cas_9line_seed.target_elevation_ft == 984
    assert "friendlies" in result.cas_9line_seed.missing_fields
    assert "egress" in result.cas_9line_seed.missing_fields


def test_stale_proposal_does_not_execute_when_target_disappears() -> None:
    store = ConfirmationStore()
    snapshots = [_snapshot(), _snapshot(alive=False)]
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", side_effect=snapshots
    ), patch("orion.mission_control_autonomy_actions.orchestrate_jtac") as orchestrate:
        pending = create_autonomy_pending_action(_decision(MissionControlAction.SUGGEST_JTAC))
        try:
            resolve_autonomy_pending_action(pending.action_id, confirm=True)
        except ValueError as exc:
            assert "stale" in str(exc)
        else:
            raise AssertionError("Expected stale proposal rejection")
    assert store.get(pending.action_id).status is ConfirmationStatus.PENDING
    orchestrate.assert_not_called()


def test_stale_proposal_does_not_cross_mission_boundary() -> None:
    store = ConfirmationStore()
    snapshots = [_snapshot(mission_id="mission-1"), _snapshot(mission_id="mission-2")]
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", side_effect=snapshots
    ), patch("orion.mission_control_autonomy_actions.orchestrate_jtac") as orchestrate:
        pending = create_autonomy_pending_action(_decision(MissionControlAction.SUGGEST_JTAC))
        try:
            resolve_autonomy_pending_action(pending.action_id, confirm=True)
        except ValueError as exc:
            assert "Mission changed" in str(exc)
        else:
            raise AssertionError("Expected stale proposal rejection")
    assert store.get(pending.action_id).status is ConfirmationStatus.PENDING
    orchestrate.assert_not_called()


def test_changed_tactical_recommendation_does_not_execute_old_action() -> None:
    store = ConfirmationStore()
    snapshot = _snapshot()
    original = _decision(MissionControlAction.SUGGEST_JTAC)
    changed = _decision(MissionControlAction.SUGGEST_9LINE)
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", return_value=snapshot
    ), patch("orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=changed), patch(
        "orion.mission_control_autonomy_actions.orchestrate_jtac"
    ) as orchestrate:
        pending = create_autonomy_pending_action(original)
        try:
            resolve_autonomy_pending_action(pending.action_id, confirm=True)
        except ValueError as exc:
            assert "Tactical recommendation changed" in str(exc)
        else:
            raise AssertionError("Expected changed recommendation rejection")
    assert store.get(pending.action_id).status is ConfirmationStatus.PENDING
    orchestrate.assert_not_called()


def test_observe_decision_cannot_create_pending_action() -> None:
    decision = MissionControlAutonomyDecision(
        action=MissionControlAction.OBSERVE,
        confidence=0.2,
        reason="nothing to do",
        requires_pilot_confirmation=False,
    )
    with patch("orion.mission_control_autonomy_actions.confirmation_store", ConfirmationStore()):
        try:
            create_autonomy_pending_action(decision)
        except ValueError as exc:
            assert "does not require pilot confirmation" in str(exc)
        else:
            raise AssertionError("Expected ValueError")
