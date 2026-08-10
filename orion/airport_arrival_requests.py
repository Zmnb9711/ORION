from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from orion.airport_arrival_runtime import ApproachType, ArrivalClearance


class ArrivalRequestIntent(StrEnum):
    REQUEST_ILS = "request_ils"
    REQUEST_TACAN = "request_tacan"
    REQUEST_VISUAL = "request_visual"
    REQUEST_LOWER = "request_lower"
    REQUEST_VECTOR = "request_vector"
    REPORT_RUNWAY_NOT_IN_SIGHT = "report_runway_not_in_sight"
    GO_AROUND = "go_around"
    UNKNOWN = "unknown"


class ArrivalRequest(BaseModel):
    intent: ArrivalRequestIntent
    raw_text: str


def classify_arrival_request(text: str) -> ArrivalRequest:
    normalized = " ".join(text.lower().strip().split())
    if any(token in normalized for token in ("ухожу на второй", "go around", "going around", "missed approach")):
        intent = ArrivalRequestIntent.GO_AROUND
    elif "ils" in normalized or "илс" in normalized:
        intent = ArrivalRequestIntent.REQUEST_ILS
    elif "tacan" in normalized or "такан" in normalized:
        intent = ArrivalRequestIntent.REQUEST_TACAN
    elif any(token in normalized for token in ("visual", "визуал", "визуально")):
        intent = ArrivalRequestIntent.REQUEST_VISUAL
    elif any(token in normalized for token in ("полосу не вижу", "runway not in sight", "negative runway")):
        intent = ArrivalRequestIntent.REPORT_RUNWAY_NOT_IN_SIGHT
    elif any(token in normalized for token in ("снизиться", "ниже", "lower", "descend")):
        intent = ArrivalRequestIntent.REQUEST_LOWER
    elif any(token in normalized for token in ("дай курс", "vector", "вектор", "heading")):
        intent = ArrivalRequestIntent.REQUEST_VECTOR
    else:
        intent = ArrivalRequestIntent.UNKNOWN
    return ArrivalRequest(intent=intent, raw_text=text)


def amend_clearance(
    clearance: ArrivalClearance,
    *,
    approach_type: ApproachType | None = None,
    heading_deg: int | None = None,
    altitude_ft: int | None = None,
    speed_kt: int | None = None,
    direct_to: str | None = None,
    frequency: str | None = None,
    pressure_setting: str | None = None,
) -> ArrivalClearance:
    data = clearance.model_dump()
    changes = {
        "approach_type": approach_type,
        "heading_deg": heading_deg,
        "altitude_ft": altitude_ft,
        "speed_kt": speed_kt,
        "direct_to": direct_to,
        "frequency": frequency,
        "pressure_setting": pressure_setting,
    }
    for key, value in changes.items():
        if value is not None:
            data[key] = value
    return ArrivalClearance.model_validate(data)
