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
        result = coalition_radio.lookup(RadioLookupQuery(text=_query_text(command.transcript)))
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
        r"\b(?:дай|назови|скажи|какая|какой|частота|частоту|юнита|группы|unit|group|frequency|what is|the)\b",
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
