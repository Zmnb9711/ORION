from unittest.mock import patch

from orion.confirmations import ConfirmationStore, PendingActionCreate
from orion.mission_control_autonomy_actions import MissionControlAutonomyResolution
from orion.mission_control_autonomy_voice import (
    AutonomyVoiceDecision,
    autonomy_proposal_text,
    parse_autonomy_voice_confirmation,
    resolve_autonomy_voice_decision,
    submit_autonomy_proposal_voice,
)
from orion.voice_core import VoiceAgent


def _pending(action_type: str = "mission_control:suggest_jtac"):
    return ConfirmationStore().create(
        PendingActionCreate(
            action_type=action_type,
            summary="test",
            payload={"target_id": "target-1", "target_name": "SA-11"},
        )
    )


def test_proposal_voice_uses_mission_control_agent() -> None:
    pending = _pending()
    command = submit_autonomy_proposal_voice(pending, language="en")
    assert command.agent is VoiceAgent.MISSION_CONTROL
    assert command.context["action_id"] == pending.action_id
    assert "Request JTAC support" in command.transcript


def test_russian_9line_proposal_text() -> None:
    pending = _pending("mission_control:suggest_9line")
    text = autonomy_proposal_text(pending, language="ru")
    assert "Подготовить 9-line CAS" in text
    assert "SA-11" in text


def test_voice_confirmation_parser_supports_ru_and_en() -> None:
    assert parse_autonomy_voice_confirmation("confirm", language="en") is True
    assert parse_autonomy_voice_confirmation("negative", language="en") is False
    assert parse_autonomy_voice_confirmation("согласен", language="ru") is True
    assert parse_autonomy_voice_confirmation("не надо", language="ru") is False


def test_ambiguous_voice_answer_does_not_resolve_action() -> None:
    pending = _pending()
    with patch("orion.mission_control_autonomy_voice.resolve_autonomy_pending_action") as resolve:
        result = resolve_autonomy_voice_decision(
            pending.action_id,
            AutonomyVoiceDecision(transcript="maybe later", language="en"),
        )
    assert result.understood is False
    assert result.confirm is None
    assert result.resolution is None
    resolve.assert_not_called()


def test_clear_voice_confirmation_resolves_named_action() -> None:
    pending = _pending()
    expected = MissionControlAutonomyResolution(pending_action=pending, executed=False)
    with patch(
        "orion.mission_control_autonomy_voice.resolve_autonomy_pending_action",
        return_value=expected,
    ) as resolve:
        result = resolve_autonomy_voice_decision(
            pending.action_id,
            AutonomyVoiceDecision(transcript="affirmative", language="en"),
        )
    assert result.understood is True
    assert result.confirm is True
    assert result.resolution == expected
    resolve.assert_called_once_with(pending.action_id, confirm=True)
