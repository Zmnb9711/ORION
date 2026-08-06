from __future__ import annotations

import re

from pydantic import BaseModel, Field

from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommandCreate


class ParsedVoiceRequest(BaseModel):
    transcript: str
    commands: list[VoiceCommandCreate] = Field(default_factory=list)


_RULES: tuple[tuple[tuple[str, ...], str, VoiceAgent, CommandPriority], ...] = (
    (("missile", "ракета"), "missile_warning", VoiceAgent.THREAT_ANALYZER, CommandPriority.CRITICAL),
    (("terrain", "земля", "pull up", "тяни"), "terrain_warning", VoiceAgent.THREAT_ANALYZER, CommandPriority.CRITICAL),
    (("fire", "пожар"), "fire_warning", VoiceAgent.THREAT_ANALYZER, CommandPriority.CRITICAL),
    (("stall", "срыв"), "stall_warning", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.CRITICAL),
    (("tanker", "танкер", "дозаправ"), "find_tanker", VoiceAgent.TANKER, CommandPriority.HIGH),
    (("tacan", "такан"), "request_tacan", VoiceAgent.TANKER, CommandPriority.HIGH),
    (("picture", "обстановк"), "request_picture", VoiceAgent.AWACS, CommandPriority.HIGH),
    (("bogey dope", "ближайш"), "request_bogey_dope", VoiceAgent.AWACS, CommandPriority.HIGH),
    (("awacs", "дрло"), "contact_awacs", VoiceAgent.AWACS, CommandPriority.HIGH),
    (("jtac", "лазер", "дым", "целеуказ"), "request_target_designation", VoiceAgent.JTAC, CommandPriority.HIGH),
    (("airport", "airfield", "аэродром"), "find_airfield", VoiceAgent.NAVIGATION, CommandPriority.NORMAL),
    (("course", "heading", "курс"), "request_heading", VoiceAgent.NAVIGATION, CommandPriority.NORMAL),
    (("checklist", "чеклист", "контрольн"), "run_checklist", VoiceAgent.CHECKLIST, CommandPriority.NORMAL),
    (("atc", "tower", "диспетчер", "вышка"), "contact_atc", VoiceAgent.ATC, CommandPriority.HIGH),
    (("cancel", "stop", "отмена", "стоп", "замолчи"), "cancel_current", VoiceAgent.SYSTEM, CommandPriority.CRITICAL),
)

_SPLIT_RE = re.compile(r"\s*(?:;|\bthen\b|\band then\b|\bзатем\b|\bпотом\b)\s*", re.IGNORECASE)


def parse_transcript(transcript: str) -> ParsedVoiceRequest:
    cleaned = transcript.strip()
    parts = [part.strip(" ,.") for part in _SPLIT_RE.split(cleaned) if part.strip(" ,.")]
    commands = [_parse_single(part) for part in parts]
    return ParsedVoiceRequest(transcript=cleaned, commands=commands)


def _parse_single(text: str) -> VoiceCommandCreate:
    normalized = text.casefold()
    for keywords, intent, agent, priority in _RULES:
        if any(keyword in normalized for keyword in keywords):
            return VoiceCommandCreate(
                transcript=text,
                intent=intent,
                agent=agent,
                priority=priority,
                context={"parser": "rules-v1"},
            )
    return VoiceCommandCreate(
        transcript=text,
        intent="general_conversation",
        agent=VoiceAgent.GENERAL_CONVERSATION,
        priority=CommandPriority.LOW,
        context={"parser": "rules-v1"},
    )
