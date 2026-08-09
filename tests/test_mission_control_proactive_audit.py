from unittest.mock import patch

from orion.confirmations import ConfirmationStatus, ConfirmationStore, PendingActionCreate
from orion.jtac_runtime import JtacDesignationMethod
from orion.mission import MissionSnapshot
from orion.mission_control_autonomy import MissionControlAction, MissionControlAutonomyDecision
from orion.mission_control_proactive import ProactiveMissionControlRuntime
from orion.orion_settings import CommunicationMode, InterfaceLanguage, OrionSettings


def _decision() -> MissionControlAutonomyDecision:
    return MissionControlAutonomyDecision(
        action=MissionControlAction.SUGGEST_JTAC,
        target_id="target-1",
        target_name="SA-11",
        confidence=0.8,
        reason="priority surface threat",
        requires_pilot_confirmation=True,
        available_designators=1,
        selected_designator_id="jtac-1",
        selected_designator_name="Axeman 1-1",
        selected_designator_supports_laser=True,
        selected_designation_method=JtacDesignationMethod.LASER,
    )


def _create_in(store: ConfirmationStore, current: MissionControlAutonomyDecision):
    return store.create(
        PendingActionCreate(
            action_type=f"mission_control:{current.action.value}",
            summary="audit proposal",
            payload={
                "target_id": current.target_id,
                "target_name": current.target_name,
                "designator_id": current.selected_designator_id,
                "designation_method": current.selected_designation_method.value,
                "confidence": current.confidence,
            },
        )
    )


def test_mission_boundary_rejects_old_pending_proposal() -> None:
    runtime = ProactiveMissionControlRuntime()
    runtime.enable()
    store = ConfirmationStore()
    decision = _decision()
    with patch("orion.mission_control_proactive.confirmation_store", store), patch(
        "orion.mission_control_proactive.evaluate_mission_control_autonomy", return_value=decision
    ), patch(
        "orion.mission_control_proactive.create_autonomy_pending_action",
        side_effect=lambda current: _create_in(store, current),
    ), patch("orion.mission_control_proactive.voice_commands.submit"):
        first = runtime.observe(MissionSnapshot(mission_id="mission-1"))
        second = runtime.observe(MissionSnapshot(mission_id="mission-2"))
    assert store.get(first.proposal.action_id).status is ConfirmationStatus.REJECTED
    assert second.proposal is not None
    assert second.proposal.action_id != first.proposal.action_id


def test_disable_rejects_active_pending_proposal() -> None:
    runtime = ProactiveMissionControlRuntime()
    runtime.enable()
    store = ConfirmationStore()
    decision = _decision()
    with patch("orion.mission_control_proactive.confirmation_store", store), patch(
        "orion.mission_control_proactive.evaluate_mission_control_autonomy", return_value=decision
    ), patch(
        "orion.mission_control_proactive.create_autonomy_pending_action",
        side_effect=lambda current: _create_in(store, current),
    ), patch("orion.mission_control_proactive.voice_commands.submit"):
        result = runtime.observe(MissionSnapshot(mission_id="mission-1"))
        runtime.disable()
    assert store.get(result.proposal.action_id).status is ConfirmationStatus.REJECTED
    assert runtime.status().active_action_id is None


def test_event_driven_language_follows_live_communication_settings() -> None:
    runtime = ProactiveMissionControlRuntime()
    runtime.enable()
    store = ConfirmationStore()
    decision = _decision()
    settings = OrionSettings(
        interface_language=InterfaceLanguage.RU,
        communication_mode=CommunicationMode.AVIATION_RUSSIAN,
    )
    with patch("orion.mission_control_proactive.confirmation_store", store), patch(
        "orion.mission_control_proactive.evaluate_mission_control_autonomy", return_value=decision
    ), patch(
        "orion.mission_control_proactive.create_autonomy_pending_action",
        side_effect=lambda current: _create_in(store, current),
    ), patch("orion.mission_control_proactive.orion_settings.get", return_value=settings), patch(
        "orion.mission_control_proactive.voice_commands.submit"
    ) as submit:
        runtime.observe(MissionSnapshot(mission_id="mission-ru"))
    payload = submit.call_args.args[0]
    assert payload.context["language"] == "ru"
    assert "Обнаружена" in payload.transcript
