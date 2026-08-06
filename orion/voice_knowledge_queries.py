from __future__ import annotations

import re

from pydantic import BaseModel, Field

from orion.aircraft_knowledge import aircraft_knowledge
from orion.knowledge_manager import OfficialKnowledgeQuery, knowledge_manager
from orion.voice_core import VoiceCommand


class VoiceKnowledgeResult(BaseModel):
    completed: bool
    spoken_text: str
    data: dict[str, object] = Field(default_factory=dict)


def execute_aircraft_knowledge_query(command: VoiceCommand) -> VoiceKnowledgeResult:
    aircraft_id = _resolve_aircraft_id(command)
    if aircraft_id is None:
        return VoiceKnowledgeResult(
            completed=False,
            spoken_text="Уточните тип самолёта или вертолёта, по руководству которого нужно выполнить поиск.",
            data={"reason": "aircraft_not_resolved"},
        )

    query_text = _clean_query(command.transcript)
    result = knowledge_manager.search(
        OfficialKnowledgeQuery(text=query_text, aircraft_id=aircraft_id, limit=3)
    )
    if not result.matches:
        profile = aircraft_knowledge.get_profile(aircraft_id)
        name = profile.display_name if profile else aircraft_id
        return VoiceKnowledgeResult(
            completed=False,
            spoken_text=f"В индексе официального руководства {name} подходящий раздел пока не найден.",
            data={"reason": "official_section_not_found", "aircraft_id": aircraft_id},
        )

    match = result.matches[0]
    page_text = f", страница {match.section.page_start}" if match.section.page_start else ""
    if match.network_required:
        spoken = (
            f"Нашёл раздел «{match.section.title}» в официальном руководстве"
            f"{page_text}. Для получения полного ответа требуется загрузить данные с сайта DCS World."
        )
    elif match.section.summary:
        spoken = f"Согласно официальному руководству, раздел «{match.section.title}»{page_text}: {match.section.summary}"
    else:
        spoken = f"Нашёл раздел «{match.section.title}» в официальном руководстве{page_text}."

    return VoiceKnowledgeResult(
        completed=True,
        spoken_text=spoken,
        data={
            "aircraft_id": aircraft_id,
            "knowledge_layer": "official",
            "document_id": match.document.document_id,
            "document_title": match.document.title,
            "document_state": match.document.state.value,
            "section": match.section.model_dump(mode="json"),
            "source_locator": match.source_locator,
            "network_required": match.network_required,
            "score": match.score,
        },
    )


def _resolve_aircraft_id(command: VoiceCommand) -> str | None:
    for key in ("aircraft_id", "current_aircraft_id", "player_aircraft_id", "context_aircraft_id"):
        value = command.context.get(key)
        if isinstance(value, str) and aircraft_knowledge.get_profile(value):
            return value

    normalized = command.transcript.casefold()
    for profile in aircraft_knowledge.list_profiles():
        names = {profile.aircraft_id, profile.display_name.casefold(), *(alias.casefold() for alias in profile.aliases)}
        if any(name in normalized for name in names):
            return profile.aircraft_id
    return None


def _clean_query(text: str) -> str:
    cleaned = re.sub(
        r"\b(?:согласно|руководству|руководство|мануал|manual|для|самолёта|самолета|модуля|dcs|как|how|do|i)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    value = " ".join(cleaned.split()).strip(" ,.?-")
    return value or text.strip()
