from __future__ import annotations

from pydantic import BaseModel, Field

from orion.confirmations import PendingAction
from orion.mission_control_autonomy import MissionControlAction, MissionControlAutonomyDecision, evaluate_mission_control_autonomy
from orion.mission_control_autonomy_actions import (
    MissionControlAutonomyResolution,
    create_autonomy_pending_action,
    resolve_autonomy_pending_action,
)
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, voice_commands


class AutonomyVoiceDecision(BaseModel):
    transcript: str = Field(min_length=1, max_length=300)
    language: str = "en"


class AutonomyVoiceDecisionResult(BaseModel):
    understood: bool
    confirm: bool | None = None
    resolution: MissionControlAutonomyResolution | None = None
    stale: bool = False
    current_decision: MissionControlAutonomyDecision | None = None
    replacement_action: PendingAction | None = None
    spoken_text: str | None = None
    voice_command: VoiceCommand | None = None


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


def submit_9line_completion_prompt(
    action_id: str,
    resolution: MissionControlAutonomyResolution,
    *,
    language: str = "en",
) -> VoiceCommand | None:
    seed = resolution.cas_9line_seed
    if seed is None:
        return None
    ru = language.casefold().startswith("ru")
    if ru:
        text = (
            f"Данные цели {seed.target_name} и целеуказателя {seed.designator_name or seed.designator_id or 'JTAC'} получены. "
            "Для завершения 9-line сообщите IP или BP, курс от IP к цели, дистанцию в морских милях, положение своих и направление выхода. "
            "Также укажите ограничения и замечания, если они есть."
        )
    else:
        text = (
            f"Target data for {seed.target_name} and designator {seed.designator_name or seed.designator_id or 'JTAC'} are available. "
            "To complete the 9-line, provide IP or BP, heading from IP to target, distance in nautical miles, friendlies, and egress. "
            "Also provide restrictions and remarks if applicable."
        )
    return voice_commands.submit(
        VoiceCommandCreate(
            transcript=text,
            intent="mission_control_autonomy_9line_completion",
            agent=VoiceAgent.MISSION_CONTROL,
            priority=CommandPriority.HIGH,
            context={
                "action_id": action_id,
                "missing_fields": ",".join(seed.missing_fields),
                "target_id": seed.target_id,
                "designator_id": seed.designator_id or "",
                "language": language,
            },
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


def _stale_voice_text(decision: MissionControlAutonomyDecision, *, language: str) -> str:
    ru = language.casefold().startswith("ru")
    target = decision.target_name or decision.target_id or ("цель" if ru else "target")
    if decision.action is MissionControlAction.OBSERVE:
        return (
            "Обстановка изменилась. Предыдущее предложение отменено; сейчас вмешательство Mission Control не требуется."
            if ru else
            "Situation changed. The previous proposal is no longer valid; Mission Control intervention is not currently required."
        )
    if decision.action is MissionControlAction.SUGGEST_9LINE:
        return (
            f"Обстановка изменилась. Предыдущее предложение устарело. Новое предложение: подготовить 9-line CAS по {target}. Подтвердите или отклоните."
            if ru else
            f"Situation changed. The previous proposal is stale. New proposal: prepare a 9-line CAS brief for {target}. Confirm or reject."
        )
    return (
        f"Обстановка изменилась. Предыдущее предложение устарело. Новое предложение: запросить JTAC по {target}. Подтвердите или отклоните."
        if ru else
        f"Situation changed. The previous proposal is stale. New proposal: request JTAC support for {target}. Confirm or reject."
    )


def _submit_stale_recovery_voice(
    old_action_id: str,
    text: str,
    *,
    language: str,
    replacement_action: PendingAction | None,
) -> VoiceCommand:
    return voice_commands.submit(
        VoiceCommandCreate(
            transcript=text,
            intent="mission_control_autonomy_stale_recovery",
            agent=VoiceAgent.MISSION_CONTROL,
            priority=CommandPriority.HIGH,
            context={
                "action_id": old_action_id,
                "replacement_action_id": replacement_action.action_id if replacement_action else "",
                "language": language,
                "stale": True,
            },
        )
    )


def resolve_autonomy_voice_decision(
    action_id: str,
    payload: AutonomyVoiceDecision,
) -> AutonomyVoiceDecisionResult:
    confirm = parse_autonomy_voice_confirmation(payload.transcript, language=payload.language)
    if confirm is None:
        return AutonomyVoiceDecisionResult(understood=False)
    try:
        resolution = resolve_autonomy_pending_action(action_id, confirm=confirm)
    except ValueError as exc:
        stale_error = "stale" in str(exc).casefold() or "changed" in str(exc).casefold()
        if confirm and stale_error:
            current = evaluate_mission_control_autonomy()
            replacement = None
            if current.requires_pilot_confirmation and current.action is not MissionControlAction.OBSERVE:
                replacement = create_autonomy_pending_action(current)
            text = _stale_voice_text(current, language=payload.language)
            command = _submit_stale_recovery_voice(
                action_id,
                text,
                language=payload.language,
                replacement_action=replacement,
            )
            return AutonomyVoiceDecisionResult(
                understood=True,
                confirm=True,
                stale=True,
                current_decision=current,
                replacement_action=replacement,
                spoken_text=text,
                voice_command=command,
            )
        raise
    command = submit_9line_completion_prompt(action_id, resolution, language=payload.language) if confirm else None
    return AutonomyVoiceDecisionResult(
        understood=True,
        confirm=confirm,
        resolution=resolution,
        spoken_text=command.transcript if command else None,
        voice_command=command,
    )
