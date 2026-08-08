from __future__ import annotations

from pydantic import BaseModel, Field

from orion.dialogue import DialogueIntent, DialogueLanguage, DialogueRequest, DialogueResult, classify_dialogue
from orion.mission_context import LiveMissionContext, SupportAsset, build_live_mission_context


FactValue = str | float | int | bool | None


class DialogueRuntimeResult(BaseModel):
    language: DialogueLanguage
    intent: DialogueIntent
    confidence: float = Field(ge=0, le=1)
    requires_confirmation: bool = False
    grounded: bool = False
    reply: str
    facts: dict[str, FactValue] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


def run_dialogue(request: DialogueRequest, context: LiveMissionContext | None = None) -> DialogueRuntimeResult:
    classification = classify_dialogue(request)
    live_context = context if context is not None else build_live_mission_context()

    if classification.requires_confirmation:
        return _from_classification(classification, issues=live_context.issues)

    if classification.intent is DialogueIntent.STATUS:
        return _status(classification, live_context)
    if classification.intent is DialogueIntent.THREATS:
        return _threats(classification, live_context)
    if classification.intent is DialogueIntent.AWACS:
        return _support(classification, live_context.awacs, "AWACS", "ДРЛО")
    if classification.intent is DialogueIntent.TANKER:
        return _support(classification, live_context.tankers, "tanker", "дозаправщик")

    return _from_classification(classification, issues=live_context.issues)


def _status(classification: DialogueResult, context: LiveMissionContext) -> DialogueRuntimeResult:
    ownship = context.ownship
    if ownship is None:
        reply = (
            "Нет актуальной телеметрии самолёта."
            if classification.language is DialogueLanguage.RU
            else "No current aircraft telemetry is available."
        )
        return _result(classification, reply=reply, grounded=False, issues=context.issues)

    altitude_ft = round(ownship.altitude_m * 3.28084)
    speed_kt = round(ownship.true_airspeed_mps * 1.94384) if ownship.true_airspeed_mps is not None else None
    heading = round(ownship.heading_deg) if ownship.heading_deg is not None else None
    facts: dict[str, FactValue] = {
        "aircraft_type": ownship.aircraft_type,
        "altitude_ft": altitude_ft,
        "true_airspeed_kt": speed_kt,
        "heading_deg": heading,
    }
    if classification.language is DialogueLanguage.RU:
        parts = [f"{ownship.aircraft_type}, высота {altitude_ft} футов"]
        if speed_kt is not None:
            parts.append(f"истинная скорость {speed_kt} узлов")
        if heading is not None:
            parts.append(f"курс {heading:03d}")
        reply = ", ".join(parts) + "."
    else:
        parts = [f"{ownship.aircraft_type}, altitude {altitude_ft} feet"]
        if speed_kt is not None:
            parts.append(f"true airspeed {speed_kt} knots")
        if heading is not None:
            parts.append(f"heading {heading:03d}")
        reply = ", ".join(parts) + "."
    return _result(classification, reply=reply, grounded=True, facts=facts, issues=context.issues)


def _threats(classification: DialogueResult, context: LiveMissionContext) -> DialogueRuntimeResult:
    if not context.hostiles:
        reply = (
            "По доступным данным обнаруженных вражеских контактов нет."
            if classification.language is DialogueLanguage.RU
            else "No detected hostile contacts in the available mission picture."
        )
        return _result(classification, reply=reply, grounded=context.available, facts={"hostile_count": 0}, issues=context.issues)

    hostile = context.hostiles[0]
    facts: dict[str, FactValue] = {
        "hostile_count": len(context.hostiles),
        "nearest_unit_id": hostile.unit_id,
        "nearest_name": hostile.name,
        "distance_km": hostile.distance_km,
        "bearing_deg": hostile.bearing_deg,
        "altitude_m": hostile.altitude_m,
    }
    if classification.language is DialogueLanguage.RU:
        reply = f"Обнаружено контактов: {len(context.hostiles)}. Ближайший — {hostile.name}"
        if hostile.bearing_deg is not None:
            reply += f", пеленг {round(hostile.bearing_deg):03d}"
        if hostile.distance_km is not None:
            reply += f", дальность {hostile.distance_km:.1f} км"
        reply += "."
    else:
        reply = f"Detected hostiles: {len(context.hostiles)}. Nearest is {hostile.name}"
        if hostile.bearing_deg is not None:
            reply += f", bearing {round(hostile.bearing_deg):03d}"
        if hostile.distance_km is not None:
            reply += f", range {hostile.distance_km:.1f} km"
        reply += "."
    return _result(classification, reply=reply, grounded=True, facts=facts, issues=context.issues)


def _support(
    classification: DialogueResult,
    assets: list[SupportAsset],
    english_role: str,
    russian_role: str,
) -> DialogueRuntimeResult:
    available = [item for item in assets if item.available and item.aar_available is not False]
    if not available:
        reply = (
            f"Доступный {russian_role} не найден в текущей картине миссии."
            if classification.language is DialogueLanguage.RU
            else f"No available {english_role} was found in the current mission picture."
        )
        return _result(classification, reply=reply, grounded=bool(assets), facts={"available_count": 0})

    asset = available[0]
    facts: dict[str, FactValue] = {
        "available_count": len(available),
        "unit_id": asset.unit_id,
        "callsign": asset.callsign,
        "frequency_mhz": asset.frequency_mhz,
        "tacan_channel": asset.tacan_channel,
        "tacan_band": asset.tacan_band,
        "distance_km": asset.distance_km,
        "bearing_deg": asset.bearing_deg,
    }
    if classification.language is DialogueLanguage.RU:
        reply = f"{russian_role.capitalize()} {asset.callsign} доступен"
        if asset.bearing_deg is not None and asset.distance_km is not None:
            reply += f", пеленг {round(asset.bearing_deg):03d}, {asset.distance_km:.1f} км"
        if asset.frequency_mhz is not None:
            reply += f", частота {asset.frequency_mhz:.3f} МГц"
        if asset.tacan_channel is not None:
            reply += f", TACAN {asset.tacan_channel}{asset.tacan_band or ''}"
        reply += "."
    else:
        reply = f"{english_role.capitalize()} {asset.callsign} is available"
        if asset.bearing_deg is not None and asset.distance_km is not None:
            reply += f", bearing {round(asset.bearing_deg):03d}, {asset.distance_km:.1f} km"
        if asset.frequency_mhz is not None:
            reply += f", frequency {asset.frequency_mhz:.3f} MHz"
        if asset.tacan_channel is not None:
            reply += f", TACAN {asset.tacan_channel}{asset.tacan_band or ''}"
        reply += "."
    return _result(classification, reply=reply, grounded=True, facts=facts)


def _from_classification(classification: DialogueResult, issues: list[str] | None = None) -> DialogueRuntimeResult:
    return DialogueRuntimeResult(
        language=classification.language,
        intent=classification.intent,
        confidence=classification.confidence,
        requires_confirmation=classification.requires_confirmation,
        grounded=False,
        reply=classification.reply,
        issues=issues or [],
    )


def _result(
    classification: DialogueResult,
    *,
    reply: str,
    grounded: bool,
    facts: dict[str, FactValue] | None = None,
    issues: list[str] | None = None,
) -> DialogueRuntimeResult:
    return DialogueRuntimeResult(
        language=classification.language,
        intent=classification.intent,
        confidence=classification.confidence,
        requires_confirmation=classification.requires_confirmation,
        grounded=grounded,
        reply=reply,
        facts=facts or {},
        issues=issues or [],
    )
