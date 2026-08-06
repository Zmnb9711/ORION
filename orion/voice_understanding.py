from __future__ import annotations

import re

from pydantic import BaseModel, Field

from orion.voice_context import VoiceConversationContext
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommandCreate


class ParsedVoiceRequest(BaseModel):
    transcript: str
    commands: list[VoiceCommandCreate] = Field(default_factory=list)


_RULES: tuple[tuple[tuple[str, ...], str, VoiceAgent, CommandPriority], ...] = (
    (("missile", "ракета"), "missile_warning", VoiceAgent.THREAT_ANALYZER, CommandPriority.CRITICAL),
    (("terrain", "земля", "pull up", "тяни"), "terrain_warning", VoiceAgent.THREAT_ANALYZER, CommandPriority.CRITICAL),
    (("fire", "пожар"), "fire_warning", VoiceAgent.THREAT_ANALYZER, CommandPriority.CRITICAL),
    (("stall", "срыв"), "stall_warning", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.CRITICAL),
    (("второй", "wingman two", "two,", "second wingman"), "command_wingman", VoiceAgent.WINGMAN, CommandPriority.HIGH),
    (("звено", "flight,"), "command_flight", VoiceAgent.FLIGHT, CommandPriority.HIGH),
    (("вертолетн", "вертолётн", "helicopter group"), "command_coalition_unit", VoiceAgent.COALITION_HELICOPTERS, CommandPriority.HIGH),
    (("наземн", "ground group", "ground unit"), "command_coalition_unit", VoiceAgent.COALITION_GROUND, CommandPriority.HIGH),
    (("кораб", "ship group", "naval group"), "command_coalition_unit", VoiceAgent.COALITION_NAVAL, CommandPriority.HIGH),
    (("частота юнита", "частота группы", "unit frequency", "group frequency"), "find_unit_frequency", VoiceAgent.COALITION_AIRCRAFT, CommandPriority.NORMAL),
    (("tacan", "такан"), "request_tacan", VoiceAgent.TANKER, CommandPriority.HIGH),
    (("frequency", "частот"), "request_frequency", VoiceAgent.TANKER, CommandPriority.HIGH),
    (("tanker", "танкер", "дозаправ"), "find_tanker", VoiceAgent.TANKER, CommandPriority.HIGH),
    (("picture", "обстановк"), "request_picture", VoiceAgent.AWACS, CommandPriority.HIGH),
    (("bogey dope", "ближайш"), "request_bogey_dope", VoiceAgent.AWACS, CommandPriority.HIGH),
    (("awacs", "дрло"), "contact_awacs", VoiceAgent.AWACS, CommandPriority.HIGH),
    (("jtac", "лазер", "дым", "целеуказ"), "request_target_designation", VoiceAgent.JTAC, CommandPriority.HIGH),
    (("airport", "airfield", "аэродром"), "find_airfield", VoiceAgent.NAVIGATION, CommandPriority.NORMAL),
    (("course", "heading", "курс"), "request_heading", VoiceAgent.NAVIGATION, CommandPriority.NORMAL),
    (("map", "карте", "карту"), "show_on_map", VoiceAgent.NAVIGATION, CommandPriority.NORMAL),
    (("checklist", "чеклист", "контрольн"), "run_checklist", VoiceAgent.CHECKLIST, CommandPriority.NORMAL),
    (("atc", "tower", "диспетчер", "вышка"), "contact_atc", VoiceAgent.ATC, CommandPriority.HIGH),
    (("cancel", "stop", "отмена", "стоп", "замолчи"), "cancel_current", VoiceAgent.SYSTEM, CommandPriority.CRITICAL),
)

_SPLIT_RE = re.compile(r"\s*(?:;|\band then\b|\bthen\b|\bзатем\b|\bпотом\b)\s*", re.IGNORECASE)


def parse_transcript(
    transcript: str,
    context: VoiceConversationContext | None = None,
) -> ParsedVoiceRequest:
    cleaned = transcript.strip()
    parts = [part.strip(" ,.") for part in _SPLIT_RE.split(cleaned) if part.strip(" ,.")]
    commands = [_parse_single(part, context) for part in parts]
    return ParsedVoiceRequest(transcript=cleaned, commands=commands)


def _parse_single(text: str, context: VoiceConversationContext | None) -> VoiceCommandCreate:
    normalized = text.casefold()
    for keywords, intent, agent, priority in _RULES:
        if any(keyword in normalized for keyword in keywords):
            return _command(text, intent, agent, priority, context)

    if context and context.active_agent is not None:
        if any(token in normalized for token in ("его", "нему", "у него", "that one", "it", "its")):
            return _command(text, "context_follow_up", context.active_agent, CommandPriority.NORMAL, context)
        if normalized in {"а tacan", "а такан", "tacan", "а частота", "частота", "frequency"}:
            intent = "request_tacan" if "tacan" in normalized or "такан" in normalized else "request_frequency"
            return _command(text, intent, context.active_agent, CommandPriority.HIGH, context)

    return _command(
        text,
        "general_conversation",
        VoiceAgent.GENERAL_CONVERSATION,
        CommandPriority.LOW,
        context,
    )


def _command(
    text: str,
    intent: str,
    agent: VoiceAgent,
    priority: CommandPriority,
    context: VoiceConversationContext | None,
) -> VoiceCommandCreate:
    payload: dict[str, str | int | float | bool | None] = {"parser": "rules-v3"}
    if context is not None:
        payload["session_id"] = context.session_id
        payload["active_subject"] = context.active_subject
        payload["previous_intent"] = context.last_intent
    return VoiceCommandCreate(
        transcript=text,
        intent=intent,
        agent=agent,
        priority=priority,
        context=payload,
    )
