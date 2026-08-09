from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from orion.confirmations import ConfirmationStatus, ConfirmationStore, PendingActionCreate
from orion.jtac_runtime import JtacDesignationMethod
from orion.mission import MissionSnapshot
from orion.mission_control_autonomy import MissionControlAction, MissionControlAutonomyDecision
from orion.mission_control_proactive import ProactiveMissionControlRuntime
from orion.voice_core import CommandPriority


def _snapshot(mission_id: str = "mission-1") -> MissionSnapshot:
    return MissionSnapshot(mission_id=mission_id)


def _decision(
    target_id: str = "target-1",
    *,
    action: MissionControlAction = MissionControlAction.SUGGEST_JTAC,
    confidence: float = 0.8,
) -> MissionControlAutonomyDecision:
    return MissionControlAutonomyDecision(
        action=action,
        target_id=target_id,
        target_name="SA-11",
        confidence=confidence,
        reason="priority surface threat",
        requires_pilot_confirmation=True,
        available_designators=1,
        selected_designator_id="jtac-1",
        selected_designator_name="Axeman 1-1",
        selected_designator_supports_laser=True,
        selected_designation_method=JtacDesignationMethod.LASER,
    )


def _observe_decision() -> MissionControlAutonomyDecision:
    return MissionControlAutonomyDecision(
        action=MissionControlAction.OBSERVE,
        confidence=0.2,
        reason="no priority threat",
        requires_pilot_confirmation=False,
    )


def _create_in(store: ConfirmationStore, current: MissionControlAutonomyDecision):
    return store.create(
        PendingActionCreate(
            action_type=f"mission_control:{current.action.value}",
            summary="proactive test",
            payload={
                "target_id": current.target_id,
                "target_name": current.target_name,
                "designator_id": current.selected_designator_id,
                "designation_method": current.selected_designation_method.value if current.selected_designation_method else None,
                "confidence": current.confidence,
            },
        )
    )


def _patch_runtime(store: ConfirmationStore, decision: MissionControlAutonomyDecision):
    return (
        patch("orion.mission_control_proactive.confirmation_store", store),
        patch("orion.mission_control_proactive.evaluate_mission_control_autonomy", return_value=decision),
        patch("orion.mission_control_proactive.create_autonomy_pending_action", side_effect=lambda current: _create_in(store, current)),
        patch("orion.mission_control_proactive.voice_commands.submit"),
    )


def test_runtime_is_quiet_until_enabled() -> None:
    runtime = ProactiveMissionControlRuntime()
    with patch("orion.mission_control_proactive.evaluate_mission_control_autonomy") as evaluate:
        result = runtime.observe(_snapshot())
    assert result.suppressed is True
    assert result.suppression_reason == "runtime disabled"
    evaluate.assert_not_called()


def test_first_action_creates_and_announces_one_proposal() -> None:
    runtime = ProactiveMissionControlRuntime()
    runtime.enable()
    store = ConfirmationStore()
    p1, p2, p3, voice = _patch_runtime(store, _decision())
    with p1, p2, p3, voice as submit:
        result = runtime.observe(_snapshot())
    assert result.proposal is not None
    assert result.proposal.status is ConfirmationStatus.PENDING
    submit.assert_called_once()
    payload = submit.call_args.args[0]
    assert payload.priority is CommandPriority.HIGH
    assert payload.context["proactive"] is True


def test_matching_pending_proposal_suppresses_duplicate() -> None:
    runtime = ProactiveMissionControlRuntime()
    runtime.enable()
    store = ConfirmationStore()
    p1, p2, p3, voice = _patch_runtime(store, _decision())
    with p1, p2, p3, voice as submit:
        first = runtime.observe(_snapshot())
        second = runtime.observe(_snapshot())
    assert second.suppressed is True
    assert second.suppression_reason == "matching proposal already pending"
    assert second.proposal.action_id == first.proposal.action_id
    assert submit.call_count == 1


def test_lateral_change_requires_replacement_hysteresis() -> None:
    runtime = ProactiveMissionControlRuntime(replacement_observations=2)
    runtime.enable()
    store = ConfirmationStore()
    decisions = [_decision("target-1"), _decision("target-2"), _decision("target-2")]
    with patch("orion.mission_control_proactive.confirmation_store", store), patch(
        "orion.mission_control_proactive.evaluate_mission_control_autonomy", side_effect=decisions
    ), patch(
        "orion.mission_control_proactive.create_autonomy_pending_action",
        side_effect=lambda current: _create_in(store, current),
    ), patch("orion.mission_control_proactive.voice_commands.submit") as submit:
        first = runtime.observe(_snapshot())
        second = runtime.observe(_snapshot())
        third = runtime.observe(_snapshot())
    assert second.suppressed is True
    assert second.suppression_reason == "replacement hysteresis active"
    assert second.proposal.action_id == first.proposal.action_id
    assert third.replaced_action_id == first.proposal.action_id
    assert store.get(first.proposal.action_id).status is ConfirmationStatus.REJECTED
    assert third.proposal.action_id != first.proposal.action_id
    replacement = submit.call_args.args[0]
    assert replacement.intent == "mission_control_proactive_proposal"
    assert replacement.context["proactive"] is True
    assert replacement.context["escalation"] is False
    assert any(marker in replacement.transcript for marker in ("Tactical picture changed", "Тактическая обстановка изменилась"))


def test_action_escalation_replaces_immediately_with_critical_callout() -> None:
    runtime = ProactiveMissionControlRuntime(replacement_observations=3)
    runtime.enable()
    store = ConfirmationStore()
    decisions = [
        _decision(action=MissionControlAction.SUGGEST_JTAC, confidence=0.75),
        _decision(action=MissionControlAction.SUGGEST_9LINE, confidence=0.9),
    ]
    with patch("orion.mission_control_proactive.confirmation_store", store), patch(
        "orion.mission_control_proactive.evaluate_mission_control_autonomy", side_effect=decisions
    ), patch(
        "orion.mission_control_proactive.create_autonomy_pending_action",
        side_effect=lambda current: _create_in(store, current),
    ), patch("orion.mission_control_proactive.voice_commands.submit") as submit:
        first = runtime.observe(_snapshot())
        second = runtime.observe(_snapshot())
    assert second.replaced_action_id == first.proposal.action_id
    assert second.suppressed is False
    assert second.proposal.action_type == "mission_control:suggest_9line"
    escalation = submit.call_args.args[0]
    assert escalation.priority is CommandPriority.CRITICAL
    assert escalation.intent == "mission_control_proactive_escalation"
    assert escalation.context["escalation"] is True
    assert any(marker in escalation.transcript for marker in ("Threat escalation", "Угроза усилилась"))


def test_confidence_escalation_replaces_immediately() -> None:
    runtime = ProactiveMissionControlRuntime(confidence_escalation_delta=0.15, replacement_observations=3)
    runtime.enable()
    store = ConfirmationStore()
    decisions = [_decision("target-1", confidence=0.6), _decision("target-2", confidence=0.8)]
    with patch("orion.mission_control_proactive.confirmation_store", store), patch(
        "orion.mission_control_proactive.evaluate_mission_control_autonomy", side_effect=decisions
    ), patch(
        "orion.mission_control_proactive.create_autonomy_pending_action",
        side_effect=lambda current: _create_in(store, current),
    ), patch("orion.mission_control_proactive.voice_commands.submit"):
        first = runtime.observe(_snapshot())
        second = runtime.observe(_snapshot())
    assert second.replaced_action_id == first.proposal.action_id
    assert second.proposal is not None


def test_deescalation_requires_consecutive_observations_and_announces_cancel() -> None:
    runtime = ProactiveMissionControlRuntime(deescalation_observations=2)
    runtime.enable()
    store = ConfirmationStore()
    decisions = [_decision(), _observe_decision(), _observe_decision()]
    with patch("orion.mission_control_proactive.confirmation_store", store), patch(
        "orion.mission_control_proactive.evaluate_mission_control_autonomy", side_effect=decisions
    ), patch(
        "orion.mission_control_proactive.create_autonomy_pending_action",
        side_effect=lambda current: _create_in(store, current),
    ), patch("orion.mission_control_proactive.voice_commands.submit") as submit:
        first = runtime.observe(_snapshot())
        second = runtime.observe(_snapshot())
        assert second.suppressed is True
        assert second.suppression_reason == "de-escalation hysteresis active"
        assert store.get(first.proposal.action_id).status is ConfirmationStatus.PENDING
        third = runtime.observe(_snapshot())
    assert third.cancelled_action_id == first.proposal.action_id
    assert store.get(first.proposal.action_id).status is ConfirmationStatus.REJECTED
    deescalation = submit.call_args.args[0]
    assert deescalation.priority is CommandPriority.NORMAL
    assert deescalation.intent == "mission_control_proactive_deescalation"


def test_single_observe_does_not_cancel_if_threat_returns() -> None:
    runtime = ProactiveMissionControlRuntime(deescalation_observations=2)
    runtime.enable()
    store = ConfirmationStore()
    decisions = [_decision(), _observe_decision(), _decision()]
    with patch("orion.mission_control_proactive.confirmation_store", store), patch(
        "orion.mission_control_proactive.evaluate_mission_control_autonomy", side_effect=decisions
    ), patch(
        "orion.mission_control_proactive.create_autonomy_pending_action",
        side_effect=lambda current: _create_in(store, current),
    ), patch("orion.mission_control_proactive.voice_commands.submit"):
        first = runtime.observe(_snapshot())
        runtime.observe(_snapshot())
        third = runtime.observe(_snapshot())
    assert third.suppressed is True
    assert third.suppression_reason == "matching proposal already pending"
    assert store.get(first.proposal.action_id).status is ConfirmationStatus.PENDING


def test_recently_resolved_signature_is_suppressed_by_cooldown() -> None:
    runtime = ProactiveMissionControlRuntime(cooldown_seconds=30)
    runtime.enable()
    store = ConfirmationStore()
    start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    p1, p2, p3, voice = _patch_runtime(store, _decision())
    with p1, p2, p3, voice:
        first = runtime.observe(_snapshot(), now=start)
        store.resolve(first.proposal.action_id, False)
        second = runtime.observe(_snapshot(), now=start + timedelta(seconds=10))
    assert second.proposal is None
    assert second.suppressed is True
    assert second.suppression_reason == "proposal cooldown active"


def test_new_mission_resets_cooldown() -> None:
    runtime = ProactiveMissionControlRuntime(cooldown_seconds=30)
    runtime.enable()
    store = ConfirmationStore()
    start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    p1, p2, p3, voice = _patch_runtime(store, _decision())
    with p1, p2, p3, voice:
        first = runtime.observe(_snapshot("mission-1"), now=start)
        store.resolve(first.proposal.action_id, False)
        second = runtime.observe(_snapshot("mission-2"), now=start + timedelta(seconds=10))
    assert second.proposal is not None
    assert second.proposal.action_id != first.proposal.action_id


def test_status_exposes_supervisor_state() -> None:
    runtime = ProactiveMissionControlRuntime(cooldown_seconds=45, replacement_observations=3)
    runtime.enable()
    store = ConfirmationStore()
    p1, p2, p3, voice = _patch_runtime(store, _decision())
    with p1, p2, p3, voice:
        result = runtime.observe(_snapshot("mission-status"))
        status = runtime.status()
    assert status.enabled is True
    assert status.mission_id == "mission-status"
    assert status.active_action_id == result.proposal.action_id
    assert status.active_target_id == "target-1"
    assert status.cooldown_seconds == 45
    assert status.replacement_required == 3
