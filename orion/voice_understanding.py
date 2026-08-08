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
    (("начни калибровку", "запусти калибровку", "start calibration", "begin calibration"), "calibration_start", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("проверь шаг", "шаг выполнен", "готово калибровка", "evaluate calibration", "check calibration step", "step complete"), "calibration_confirm_step", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("повтори шаг калибровки", "повторить калибровку", "retry calibration", "retry calibration step"), "calibration_retry", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("повтори инструкцию", "что делать калибровка", "repeat calibration instruction", "repeat instruction"), "calibration_repeat_instruction", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("статус калибровки", "какой шаг калибровки", "calibration status", "calibration step"), "calibration_status", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("почему я ещё не ready", "почему я еще не ready", "готов ли orion", "готов к полёту", "готов к полету", "ready to fly", "why am i not ready", "are we ready to fly"), "cockpit_readiness_query", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("какой у меня tacan", "какой у меня такан", "мой tacan", "мой такан", "текущий tacan", "текущий такан", "what is my tacan", "current tacan"), "cockpit_tacan_query", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("какой у меня comm1", "какой comm1", "мой comm1", "текущий comm1", "what is my comm1", "current comm1"), "cockpit_comm1_query", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("какой у меня comm2", "какой comm2", "мой comm2", "текущий comm2", "what is my comm2", "current comm2"), "cockpit_comm2_query", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("контекст миссии", "что в миссии", "mission context", "mission summary"), "mission_context_summary", VoiceAgent.MISSION_CONTROL, CommandPriority.NORMAL),
    (("какие awacs доступны", "какие дрло доступны", "доступные awacs", "available awacs", "list awacs"), "list_awacs", VoiceAgent.AWACS, CommandPriority.NORMAL),
    (("какие танкеры доступны", "доступные танкеры", "available tankers", "list tankers"), "list_tankers", VoiceAgent.TANKER, CommandPriority.NORMAL),
    (("какие jtac доступны", "доступные jtac", "available jtac", "list jtac"), "list_jtac", VoiceAgent.JTAC, CommandPriority.NORMAL),
    (("ближайший противник", "где ближайший противник", "nearest hostile", "nearest enemy"), "nearest_hostile", VoiceAgent.AWACS, CommandPriority.HIGH),
    (("ближайший дружественный", "кто из своих ближе", "nearest friendly"), "nearest_friendly", VoiceAgent.MISSION_CONTROL, CommandPriority.NORMAL),
    (("где ближайший танкер", "nearest tanker", "where is the tanker"), "nearest_tanker", VoiceAgent.TANKER, CommandPriority.NORMAL),
    (("где ближайший awacs", "где ближайший дрло", "nearest awacs", "where is awacs"), "nearest_awacs", VoiceAgent.AWACS, CommandPriority.NORMAL),
    (("начать дозаправку", "начни дозаправку", "начать сближение с танкером", "start aerial refueling", "start aar", "begin rendezvous"), "aar_start", VoiceAgent.TANKER, CommandPriority.HIGH),
    (("статус сближения", "статус дозаправки", "где мы по дозаправке", "aar status", "rendezvous status", "refueling status"), "aar_status", VoiceAgent.TANKER, CommandPriority.NORMAL),
    (("pre-contact", "pre contact", "предконтакт"), "aar_pre_contact", VoiceAgent.TANKER, CommandPriority.HIGH),
    (("contact", "контакт с танкером"), "aar_contact", VoiceAgent.TANKER, CommandPriority.HIGH),
    (("дозаправка завершена", "закончил дозаправку", "refueling complete", "aar complete"), "aar_complete", VoiceAgent.TANKER, CommandPriority.NORMAL),
    (("отмена дозаправки", "отмени дозаправку", "прервать дозаправку", "abort refueling", "abort aar"), "aar_abort", VoiceAgent.TANKER, CommandPriority.CRITICAL),
    (("согласно руководству", "в руководстве", "по руководству", "мануал", "manual", "как выполнить", "как настроить", "что делать при", "почему не работает", "how do i", "according to the manual"), "aircraft_knowledge_query", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("ufc", "уфк", "left ddi", "right ddi", "левый ddi", "правый ddi", "mpcd", "sensor control switch", "comm1 preset", "comm2 preset", "канал comm1", "канал comm2"), "aircraft_knowledge_query", VoiceAgent.FLIGHT_ADVISOR, CommandPriority.NORMAL),
    (("канал рсбн", "каналы рсбн", "рсбн канал", "rsbn channel", "rsbn preset"), "find_rsbn_channel", VoiceAgent.NAVIGATION, CommandPriority.NORMAL),
    (("канал арк", "каналы арк", "арк канал", "adf channel", "adf preset", "ndb preset"), "find_adf_channel", VoiceAgent.NAVIGATION, CommandPriority.NORMAL),
    (("предустановленный канал", "предустановленные каналы", "канал радио", "радиоканал", "radio preset", "preset channel"), "find_radio_preset_channel", VoiceAgent.NAVIGATION, CommandPriority.NORMAL),
    (("позывные юнитов около", "позывные около", "кто у нас рядом с", "кто рядом с", "units near", "callsigns near", "who is near", "units around"), "find_unit_callsigns_near_landmark", VoiceAgent.COALITION_AIRCRAFT, CommandPriority.NORMAL),
    (("какой позывной", "какие позывные", "назови позывной", "назови позывные", "callsign", "callsigns"), "find_unit_callsign", VoiceAgent.COALITION_AIRCRAFT, CommandPriority.NORMAL),
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
_PRONOUNS = ("его", "нему", "у него", "он", "его сейчас", "that one", "it", "its", "him")
_NAMED_FREQUENCY_RE = re.compile(r"(?:частот(?:а|у|ы)?|frequency)\s+(?:of\s+)?([\w][\w .-]*\d[\w .-]*|[A-Za-z][A-Za-z .-]+\s+\d+)", re.IGNORECASE)


def parse_transcript(transcript: str, context: VoiceConversationContext | None = None) -> ParsedVoiceRequest:
    cleaned = transcript.strip()
    parts = [part.strip(" ,.") for part in _SPLIT_RE.split(cleaned) if part.strip(" ,.")]
    commands = [_parse_single(part, context) for part in parts]
    return ParsedVoiceRequest(transcript=cleaned, commands=commands)


def _parse_single(text: str, context: VoiceConversationContext | None) -> VoiceCommandCreate:
    normalized = text.casefold()
    if context and context.active_subject:
        refers_to_subject = any(token in normalized for token in _PRONOUNS)
        if refers_to_subject or normalized in {"а частота", "частота", "frequency", "а где", "где сейчас"}:
            contextual_agent = context.active_agent or VoiceAgent.COALITION_AIRCRAFT
            if any(token in normalized for token in ("частот", "frequency")):
                intent = "request_frequency" if contextual_agent is VoiceAgent.TANKER else "find_unit_frequency"
                priority = CommandPriority.HIGH if contextual_agent is VoiceAgent.TANKER else CommandPriority.NORMAL
                return _command(text, intent, contextual_agent, priority, context)
            if any(token in normalized for token in ("карте", "карту", "map")):
                return _command(text, "show_unit_on_map", contextual_agent, CommandPriority.NORMAL, context)
            if any(token in normalized for token in ("где", "положен", "координат", "where", "position", "location")):
                return _command(text, "find_unit_position", contextual_agent, CommandPriority.NORMAL, context)
            return _command(text, "context_follow_up", contextual_agent, CommandPriority.NORMAL, context)

    if _NAMED_FREQUENCY_RE.search(text):
        return _command(text, "find_unit_frequency", VoiceAgent.COALITION_AIRCRAFT, CommandPriority.NORMAL, context)

    for keywords, intent, agent, priority in _RULES:
        if any(keyword in normalized for keyword in keywords):
            return _command(text, intent, agent, priority, context)

    if context and context.active_agent is not None:
        if normalized in {"а tacan", "а такан", "tacan"}:
            return _command(text, "request_tacan", context.active_agent, CommandPriority.HIGH, context)

    return _command(text, "general_conversation", VoiceAgent.GENERAL_CONVERSATION, CommandPriority.LOW, context)


def _command(text: str, intent: str, agent: VoiceAgent, priority: CommandPriority, context: VoiceConversationContext | None) -> VoiceCommandCreate:
    payload: dict[str, str | int | float | bool | None] = {"parser": "rules-v8"}
    if context is not None:
        payload["session_id"] = context.session_id
        payload["active_subject"] = context.active_subject
        payload["previous_intent"] = context.last_intent
        for key in ("unit_id", "callsign", "unit_type", "landmark_id", "landmark_name", "aircraft_id"):
            if value := context.entities.get(key):
                payload[f"context_{key}"] = value
    return VoiceCommandCreate(transcript=text, intent=intent, agent=agent, priority=priority, context=payload)
