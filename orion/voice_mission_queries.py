from __future__ import annotations

import re

from pydantic import BaseModel, Field

from orion.coalition_radio import (
    CallsignLookupQuery,
    NearbyCallsignQuery,
    RadioLookupQuery,
    coalition_radio,
)
from orion.mission_readiness import require_current_mission_data
from orion.voice_core import VoiceCommand


class VoiceMissionQueryResult(BaseModel):
    completed: bool
    spoken_text: str
    data: dict[str, object] = Field(default_factory=dict)


_RADIUS_RE = re.compile(r"(?:в радиусе|within)\s+(\d+(?:[.,]\d+)?)\s*(?:км|километр(?:а|ов)?|km)", re.IGNORECASE)
_LANDMARK_PATTERNS = (
    re.compile(r"(?:около|рядом с|возле)\s+(.+?)(?:\s+в радиусе|$)", re.IGNORECASE),
    re.compile(r"(?:near|around)\s+(.+?)(?:\s+within|$)", re.IGNORECASE),
)


def execute_mission_query(command: VoiceCommand) -> VoiceMissionQueryResult:
    """Resolve informational voice intents against current Mission Bridge indexes."""
    try:
        require_current_mission_data()
    except RuntimeError:
        return VoiceMissionQueryResult(
            completed=False,
            spoken_text="Данные Mission Bridge недоступны или устарели.",
            data={"reason": "mission_data_unavailable"},
        )

    if command.intent == "find_unit_frequency":
        result = coalition_radio.lookup(RadioLookupQuery(text=_subject_or_query(command)))
        return VoiceMissionQueryResult(
            completed=result.found,
            spoken_text=result.message,
            data={"unit": result.unit.model_dump(mode="json") if result.unit else None},
        )

    if command.intent == "find_unit_callsign":
        result = coalition_radio.lookup_callsigns(CallsignLookupQuery(text=_optional_query_text(command.transcript)))
        return VoiceMissionQueryResult(
            completed=result.found,
            spoken_text=result.message,
            data={"units": [unit.model_dump(mode="json") for unit in result.units]},
        )

    if command.intent in {"find_unit_position", "show_unit_on_map"}:
        unit = _find_context_unit(command)
        if unit is None:
            return VoiceMissionQueryResult(
                completed=False,
                spoken_text="Не удалось определить, о каком юните идёт речь.",
                data={"reason": "unit_context_missing"},
            )
        if unit.point is None:
            return VoiceMissionQueryResult(
                completed=False,
                spoken_text=f"Для {unit.callsign}, {unit.spoken_type}, координаты в текущих данных миссии отсутствуют.",
                data={"reason": "unit_position_missing", "unit": unit.model_dump(mode="json")},
            )
        coordinates = {"x_m": unit.point.x_m, "z_m": unit.point.z_m}
        if command.intent == "show_unit_on_map":
            text = f"Показываю {unit.callsign}, {unit.spoken_type}, на карте."
            action = "show_unit_on_map"
        else:
            text = (
                f"{unit.callsign}, {unit.spoken_type}: координаты X {unit.point.x_m:.0f}, "
                f"Z {unit.point.z_m:.0f} метров."
            )
            action = "report_unit_position"
        return VoiceMissionQueryResult(
            completed=True,
            spoken_text=text,
            data={
                "action": action,
                "unit": unit.model_dump(mode="json"),
                "coordinates": coordinates,
            },
        )

    if command.intent == "find_unit_callsigns_near_landmark":
        landmark = _extract_landmark(command.transcript)
        if not landmark:
            return VoiceMissionQueryResult(
                completed=False,
                spoken_text="Не удалось определить ориентир. Назовите город, аэродром или точку миссии.",
                data={"reason": "landmark_missing"},
            )
        result = coalition_radio.lookup_near_landmark(
            NearbyCallsignQuery(
                landmark=landmark,
                radius_km=_extract_radius_km(command.transcript),
            )
        )
        return VoiceMissionQueryResult(
            completed=result.found,
            spoken_text=result.message,
            data={
                "landmark": result.landmark.model_dump(mode="json") if result.landmark else None,
                "units": [item.model_dump(mode="json") for item in result.units],
            },
        )

    return VoiceMissionQueryResult(
        completed=False,
        spoken_text="Этот информационный запрос пока не поддерживается.",
        data={"reason": "unsupported_intent"},
    )


def _find_context_unit(command: VoiceCommand):
    subject = _context_subject(command)
    if not subject:
        subject = _query_text(command.transcript)
    result = coalition_radio.lookup_callsigns(CallsignLookupQuery(text=subject))
    return result.units[0] if result.units else None


def _context_subject(command: VoiceCommand) -> str | None:
    for key in ("context_unit_id", "context_callsign", "active_subject"):
        value = command.context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _subject_or_query(command: VoiceCommand) -> str:
    return _context_subject(command) or _query_text(command.transcript)


def _extract_radius_km(text: str) -> float:
    match = _RADIUS_RE.search(text)
    if not match:
        return 50.0
    return float(match.group(1).replace(",", "."))


def _extract_landmark(text: str) -> str | None:
    for pattern in _LANDMARK_PATTERNS:
        match = pattern.search(text.strip(" .?"))
        if match:
            return match.group(1).strip(" .?")
    return None


def _query_text(text: str) -> str:
    cleaned = re.sub(
        r"\b(?:дай|назови|скажи|какая|какой|где|сейчас|покажи|частота|частоту|юнита|группы|unit|group|frequency|where|show|what is|the|it|him|он|его|у него)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return " ".join(cleaned.split()).strip(" ,.?-") or text.strip()


def _optional_query_text(text: str) -> str | None:
    cleaned = re.sub(
        r"\b(?:дай|назови|скажи|какой|какие|позывной|позывные|юнита|юнитов|callsign|callsigns|unit|units|available)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    value = " ".join(cleaned.split()).strip(" ,.?-")
    return value or None
