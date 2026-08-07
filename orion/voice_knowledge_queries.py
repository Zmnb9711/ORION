from __future__ import annotations

import re

from pydantic import BaseModel, Field

from orion.aircraft_knowledge import aircraft_knowledge
from orion.fa18c_cockpit import fa18c_cockpit
from orion.fa18c_live_state import advise_hornet_live_state
from orion.fa18c_systems import fa18c_knowledge_pack
from orion.knowledge_manager import OfficialKnowledgeQuery, knowledge_manager
from orion.voice_core import VoiceCommand


class VoiceKnowledgeResult(BaseModel):
    completed: bool
    spoken_text: str
    data: dict[str, object] = Field(default_factory=dict)


def execute_aircraft_knowledge_query(command: VoiceCommand) -> VoiceKnowledgeResult:
    aircraft_id = _resolve_aircraft_id(command)
    if aircraft_id is None:
        return VoiceKnowledgeResult(completed=False, spoken_text="Уточните тип самолёта или вертолёта, по руководству которого нужно выполнить поиск.", data={"reason": "aircraft_not_resolved"})

    query_text = _clean_query(command.transcript)

    if aircraft_id == "fa-18c" and not _explicit_official_request(command.transcript):
        live = advise_hornet_live_state(command.transcript, command.context)
        if live is not None:
            return VoiceKnowledgeResult(completed=True, spoken_text=live.spoken_text, data={"aircraft_id": "fa-18c", "knowledge_layer": "live_hornet_cockpit", "topic": live.topic, "observed": live.observed, "next_actions": live.next_actions, "network_required": False})
        structured = _execute_hornet_structured_query(query_text, procedures_only=_procedure_execution_request(command.transcript))
        if structured is not None:
            return structured

    result = knowledge_manager.search(OfficialKnowledgeQuery(text=query_text, aircraft_id=aircraft_id, limit=3))
    if not result.matches:
        profile = aircraft_knowledge.get_profile(aircraft_id)
        name = profile.display_name if profile else aircraft_id
        return VoiceKnowledgeResult(completed=False, spoken_text=f"В индексе официального руководства {name} подходящий раздел пока не найден.", data={"reason": "official_section_not_found", "aircraft_id": aircraft_id})

    match = result.matches[0]
    page_text = f", страница {match.section.page_start}" if match.section.page_start else ""
    if match.network_required:
        spoken = f"Нашёл раздел «{match.section.title}» в официальном руководстве{page_text}. Для получения полного ответа требуется загрузить данные с сайта DCS World."
    elif match.section.summary:
        spoken = f"Согласно официальному руководству, раздел «{match.section.title}»{page_text}: {match.section.summary}"
    else:
        spoken = f"Нашёл раздел «{match.section.title}» в официальном руководстве{page_text}."
    return VoiceKnowledgeResult(completed=True, spoken_text=spoken, data={"aircraft_id": aircraft_id, "knowledge_layer": "official", "document_id": match.document.document_id, "document_title": match.document.title, "document_state": match.document.state.value, "section": match.section.model_dump(mode="json"), "source_locator": match.source_locator, "network_required": match.network_required, "score": match.score})


def _execute_hornet_structured_query(query_text: str, *, procedures_only: bool = False) -> VoiceKnowledgeResult | None:
    candidates = _structured_candidates(query_text)
    if not procedures_only:
        for candidate in candidates:
            cockpit_matches = fa18c_cockpit.find(candidate)
            if cockpit_matches:
                item = cockpit_matches[0]
                spoken = f"{item.title}: находится {item.location} {item.purpose} {item.interaction}"
                return VoiceKnowledgeResult(completed=True, spoken_text=spoken, data={"aircraft_id": "fa-18c", "knowledge_layer": "structured_hornet_cockpit", "control": item.model_dump(mode="json"), "network_required": False})
    for candidate in candidates:
        found = fa18c_knowledge_pack.find(candidate)
        procedures = found["procedures"]
        systems = found["systems"]
        if procedures:
            item = procedures[0]
            phases = "; затем ".join(item.ordered_phases)
            return VoiceKnowledgeResult(completed=True, spoken_text=f"{item.title}. Порядок: {phases}.", data={"aircraft_id": "fa-18c", "knowledge_layer": "structured_hornet_procedure", "procedure": item.model_dump(mode="json"), "network_required": False})
        if systems and not procedures_only:
            item = systems[0]
            return VoiceKnowledgeResult(completed=True, spoken_text=f"{item.title}: {item.summary}", data={"aircraft_id": "fa-18c", "knowledge_layer": "structured_hornet_system", "system": item.model_dump(mode="json"), "network_required": False})
    return None


def _structured_candidates(query_text: str) -> list[str]:
    candidates = [query_text]
    stop = {"настроить", "настройка", "включить", "выбрать", "использовать", "показать", "setup", "set", "select", "use"}
    for token in re.findall(r"[\w/-]+", query_text.casefold()):
        if len(token) >= 3 and token not in stop and token not in candidates:
            candidates.append(token)
    return candidates


def _explicit_official_request(text: str) -> bool:
    normalized = text.casefold()
    return any(phrase in normalized for phrase in ("согласно руководству", "в руководстве", "по руководству", "руководство", "мануал", "manual", "according to the manual"))


def _procedure_execution_request(text: str) -> bool:
    normalized = text.casefold()
    return any(phrase in normalized for phrase in ("как выполнить", "how do i perform", "how to perform"))


def _resolve_aircraft_id(command: VoiceCommand) -> str | None:
    for key in ("aircraft_id", "current_aircraft_id", "player_aircraft_id", "context_aircraft_id"):
        value = command.context.get(key)
        if isinstance(value, str):
            resolved = aircraft_knowledge.resolve_aircraft_id(value)
            if resolved:
                return resolved
    normalized = command.transcript.casefold()
    for profile in aircraft_knowledge.list_profiles():
        names = {profile.aircraft_id, profile.display_name.casefold(), *(alias.casefold() for alias in profile.aliases)}
        if any(name in normalized for name in names):
            return profile.aircraft_id
    return None


def _clean_query(text: str) -> str:
    cleaned = re.sub(r"\b(?:согласно|руководству|руководство|мануал|manual|для|самолёта|самолета|модуля|dcs|как|how|do|i|где|находится|where|is|the)\b", " ", text, flags=re.IGNORECASE)
    value = " ".join(cleaned.split()).strip(" ,.?-")
    return value or text.strip()
