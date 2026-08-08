from unittest.mock import patch

from orion.cas_9line import Cas9LineState, Cas9LineStore
from orion.confirmations import ConfirmationStatus, ConfirmationStore
from orion.jtac_runtime import JtacDesignationMethod
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_control_autonomy import MissionControlAction, MissionControlAutonomyDecision
from orion.mission_control_autonomy_actions import (
    Cas9LineAutonomyCompletion,
    complete_autonomy_9line,
    create_autonomy_pending_action,
    resolve_autonomy_pending_action,
)
from orion.mission_control_jtac import MissionControlJtacResult


def _decision(
    action: MissionControlAction,
    *,
    method: JtacDesignationMethod | None = JtacDesignationMethod.LASER,
    designator_id: str | None = "jtac-1",
    target_id: str = "target-1",
) -> MissionControlAutonomyDecision:
    return MissionControlAutonomyDecision(
        action=action,
        target_id=target_id if action is not MissionControlAction.OBSERVE else None,
        target_name="SA-11" if target_id == "target-1" else "SA-15",
        confidence=0.9,
        reason="test",
        requires_pilot_confirmation=action is not MissionControlAction.OBSERVE,
        available_designators=1,
        selected_designator_id=designator_id,
        selected_designator_name="Axeman 1-1" if designator_id else None,
        selected_designator_supports_laser=method is JtacDesignationMethod.LASER,
        selected_designator_supports_smoke=method is JtacDesignationMethod.SMOKE,
        selected_designation_method=method,
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


def _completion() -> Cas9LineAutonomyCompletion:
    return Cas9LineAutonomyCompletion(
        ip_or_bp="FORD",
        heading_deg=270,
        distance_nm=6,
        friendlies="south 2 km",
        egress="east",
        restrictions="remain north",
        remarks="final attack heading 240-300",
        language="en",
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


def test_confirmed_jtac_proposal_executes_selected_laser_method() -> None:
    store = ConfirmationStore()
    snapshot = _snapshot()
    decision = _decision(MissionControlAction.SUGGEST_JTAC, method=JtacDesignationMethod.LASER)
    jtac_result = MissionControlJtacResult(accepted=True, target_id="target-1", spoken_text="JTAC assigned")
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", return_value=snapshot
    ), patch("orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=decision), patch(
        "orion.mission_control_autonomy_actions.orchestrate_jtac", return_value=jtac_result
    ) as orchestrate:
        pending = create_autonomy_pending_action(decision)
        result = resolve_autonomy_pending_action(pending.action_id, confirm=True)
    request = orchestrate.call_args.args[0]
    assert result.pending_action.status is ConfirmationStatus.CONFIRMED
    assert result.executed is True
    assert request.target_id == "target-1"
    assert request.requested_asset_id == "jtac-1"
    assert request.method is JtacDesignationMethod.LASER
    assert request.laser_code == 1688


def test_confirmed_smoke_only_jtac_uses_smoke_method() -> None:
    store = ConfirmationStore()
    snapshot = _snapshot()
    decision = _decision(MissionControlAction.SUGGEST_JTAC, method=JtacDesignationMethod.SMOKE)
    jtac_result = MissionControlJtacResult(accepted=True, target_id="target-1", spoken_text="JTAC assigned")
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", return_value=snapshot
    ), patch("orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=decision), patch(
        "orion.mission_control_autonomy_actions.orchestrate_jtac", return_value=jtac_result
    ) as orchestrate:
        pending = create_autonomy_pending_action(decision)
        result = resolve_autonomy_pending_action(pending.action_id, confirm=True)
    request = orchestrate.call_args.args[0]
    assert result.executed is True
    assert request.method is JtacDesignationMethod.SMOKE
    assert request.laser_code is None


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
    assert result.cas_9line_seed.designator_id == "jtac-1"
    assert "distance_nm" in result.cas_9line_seed.missing_fields
    assert "friendlies" in result.cas_9line_seed.missing_fields
    assert "restrictions" in result.cas_9line_seed.missing_fields


def test_confirmed_9line_completion_creates_real_cas_draft() -> None:
    store = ConfirmationStore()
    cas_store = Cas9LineStore()
    snapshot = _snapshot()
    decision = _decision(MissionControlAction.SUGGEST_9LINE)
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.cas_9line_store", cas_store
    ), patch("orion.mission_control_autonomy_actions.mission_store.get", return_value=snapshot), patch(
        "orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=decision
    ):
        pending = create_autonomy_pending_action(decision)
        resolve_autonomy_pending_action(pending.action_id, confirm=True)
        brief = complete_autonomy_9line(pending.action_id, _completion())
    assert brief.state is Cas9LineState.DRAFT
    assert brief.source_action_id == pending.action_id
    assert brief.target_id == "target-1"
    assert brief.target_location == "41.123457, 41.765432"
    assert brief.target_elevation_ft == 984
    assert brief.requested_asset_id == "jtac-1"
    assert brief.laser_code == 1688
    assert brief.mark == "laser 1688"
    assert brief.ip_or_bp == "FORD"
    assert brief.restrictions == "remain north"


def test_9line_completion_is_idempotent_per_autonomy_action() -> None:
    store = ConfirmationStore()
    cas_store = Cas9LineStore()
    snapshot = _snapshot()
    decision = _decision(MissionControlAction.SUGGEST_9LINE)
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.cas_9line_store", cas_store
    ), patch("orion.mission_control_autonomy_actions.mission_store.get", return_value=snapshot), patch(
        "orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=decision
    ):
        pending = create_autonomy_pending_action(decision)
        resolve_autonomy_pending_action(pending.action_id, confirm=True)
        first = complete_autonomy_9line(pending.action_id, _completion())
        second = complete_autonomy_9line(pending.action_id, _completion())
    assert first.brief_id == second.brief_id
    assert len(cas_store.list()) == 1


def test_stale_target_closes_old_action_and_creates_replacement() -> None:
    store = ConfirmationStore()
    snapshots = [_snapshot(), _snapshot(alive=False), _snapshot(alive=False)]
    current = _decision(MissionControlAction.SUGGEST_JTAC, target_id="target-2")
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", side_effect=snapshots
    ), patch("orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=current), patch(
        "orion.mission_control_autonomy_actions.orchestrate_jtac"
    ) as orchestrate:
        pending = create_autonomy_pending_action(_decision(MissionControlAction.SUGGEST_JTAC))
        result = resolve_autonomy_pending_action(pending.action_id, confirm=True)
    assert result.stale is True
    assert result.pending_action.status is ConfirmationStatus.REJECTED
    assert result.replacement_action is not None
    assert result.replacement_action.action_id != pending.action_id
    assert result.replacement_action.status is ConfirmationStatus.PENDING
    orchestrate.assert_not_called()


def test_stale_mission_can_fall_back_to_observe_without_replacement() -> None:
    store = ConfirmationStore()
    snapshots = [_snapshot(mission_id="mission-1"), _snapshot(mission_id="mission-2")]
    current = _decision(MissionControlAction.OBSERVE)
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", side_effect=snapshots
    ), patch("orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=current):
        pending = create_autonomy_pending_action(_decision(MissionControlAction.SUGGEST_JTAC))
        result = resolve_autonomy_pending_action(pending.action_id, confirm=True)
    assert result.stale is True
    assert result.pending_action.status is ConfirmationStatus.REJECTED
    assert result.current_decision.action is MissionControlAction.OBSERVE
    assert result.replacement_action is None


def test_changed_designation_method_replaces_old_proposal() -> None:
    store = ConfirmationStore()
    snapshot = _snapshot()
    original = _decision(MissionControlAction.SUGGEST_JTAC, method=JtacDesignationMethod.LASER)
    changed = _decision(MissionControlAction.SUGGEST_JTAC, method=JtacDesignationMethod.SMOKE)
    with patch("orion.mission_control_autonomy_actions.confirmation_store", store), patch(
        "orion.mission_control_autonomy_actions.mission_store.get", return_value=snapshot
    ), patch("orion.mission_control_autonomy_actions.evaluate_mission_control_autonomy", return_value=changed), patch(
        "orion.mission_control_autonomy_actions.orchestrate_jtac"
    ) as orchestrate:
        pending = create_autonomy_pending_action(original)
        result = resolve_autonomy_pending_action(pending.action_id, confirm=True)
    assert result.stale is True
    assert result.pending_action.status is ConfirmationStatus.REJECTED
    assert result.replacement_action is not None
    assert result.replacement_action.payload["designation_method"] == "smoke"
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
