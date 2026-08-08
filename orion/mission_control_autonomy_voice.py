from __future__ import annotations

from pydantic import BaseModel, Field

from orion.confirmations import PendingAction
from orion.mission_control_autonomy_actions import MissionControlAutonomyResolution, resolve_autonomy_pending_action
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, voice_commands


class AutonomyVoiceDecision(BaseModel):
    transcript: str = Field(min_length=1, max_length=300)
    language: str = "en"


class AutonomyVoiceDecisionResult(BaseModel):
    understood: bool
    confirm: bool | None = None
    resolution: MissionControlAutonomyResolution | None = None


def autonomy_proposal_text(action: PendingAction, *, language: str = "en") -> str:
    ru = language.casefold().startswith("ru")
    target = str(action.payload.get("target_name") or action.payload.get("target_id") or "target")
    if action.action_type == "mission_control:suggest_9line":
        if ru:
            return f"Обнаружена приоритетная наземная угроза {target}. Подготовить 9-line CAS? Подтвердите или отклоните."
        return f"Priority surface threat {target} detected. Prepare a 9-line CAS brief? Confirm or reject."
    if action.action_type == "mission_control:suggest_jtac":
        if ru:
            return f"Обнаружена наземная угроза {target}. Запросить поддержку JTAC? Подтвердите или отклоните."
        return f"Surface threat {target} detected. Request JTAC support? Confirm or reject."
    return (f"Подтвердить действие Mission Control: {action.summary}?" if ru else f"Confirm Mission Control action: {action.summary}?")


def submit_autonomy_proposal_voice(action: PendingAction, *, language: str = "en") -> VoiceCommand:
    return voice_commands.submit(
        VoiceCommandCreate(
            transcript=autonomy_proposal_text(action, language=language),
            intent="mission_control_autonomy_confirmation",
            agent=VoiceAgent.MISSION_CONTROL,
            priority=CommandPriority.HIGH,
            context={"action_id": action.action_id, "action_type": action.action_type, "language": language},
        )
    )


def parse_autonomy_voice_confirmation(transcript: str, *, language: str = "en") -> bool | None:
    normalized = " ".join(transcript.casefold().strip().split())
    ru = language.casefold().startswith("ru")
    positives = {
        "да", "подтверждаю", "подтвердить", "выполняй", "делай", "согласен", "принято",
    } if ru else {
        "yes", "confirm", "confirmed", "affirm", "affirmative", "go ahead", "do it", "approved",
    }
    negatives = {
        "нет", "отклоняю", "отклонить", "отмена", "отменить", "не надо", "не нужно",
    } if ru else {
        "no", "reject", "rejected", "negative", "cancel", "abort", "do not", "don't",
    }
    if normalized in positives:
        return True
    if normalized in negatives:
        return False
    return None


def resolve_autonomy_voice_decision(
    action_id: str,
    payload: AutonomyVoiceDecision,
) -> AutonomyVoiceDecisionResult:
    confirm = parse_autonomy_voice_confirmation(payload.transcript, language=payload.language)
    if confirm is None:
        return AutonomyVoiceDecisionResult(understood=False)
    resolution = resolve_autonomy_pending_action(action_id, confirm=confirm)
    return AutonomyVoiceDecisionResult(understood=True, confirm=confirm, resolution=resolution)
