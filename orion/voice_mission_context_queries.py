from __future__ import annotations

from pydantic import BaseModel, Field

from orion.mission_context import LiveMissionContext, MissionContact, SupportAsset, build_live_mission_context


class MissionContextVoiceResult(BaseModel):
    completed: bool
    spoken_text: str
    data: dict[str, object] = Field(default_factory=dict)


def execute_mission_context_query(intent: str, transcript: str) -> MissionContextVoiceResult:
    context = build_live_mission_context()
    language = _language(transcript)

    if not context.available:
        text = "Данные Mission Bridge недоступны." if language == "ru" else "Mission Bridge data is unavailable."
        return MissionContextVoiceResult(False, text, {"issues": context.issues})

    if intent == "mission_context_summary":
        return _summary(context, language)
    if intent == "list_awacs":
        return _support_list(context.awacs, "AWACS", language)
    if intent == "list_tankers":
        return _support_list(context.tankers, "танкеры" if language == "ru" else "tankers", language)
    if intent == "list_jtac":
        return _support_list(context.jtac, "JTAC", language)
    if intent == "nearest_hostile":
        return _nearest_contact(context.hostiles, hostile=True, language=language)
    if intent == "nearest_friendly":
        return _nearest_contact(context.friendlies, hostile=False, language=language)
    if intent == "nearest_tanker":
        return _nearest_support(context.tankers, "танкер" if language == "ru" else "tanker", language)
    if intent == "nearest_awacs":
        return _nearest_support(context.awacs, "AWACS", language)

    return MissionContextVoiceResult(False, "Этот запрос контекста миссии пока не поддерживается." if language == "ru" else "This mission-context query is not supported yet.")


def _summary(context: LiveMissionContext, language: str) -> MissionContextVoiceResult:
    friendlies = len(context.friendlies)
    hostiles = len(context.hostiles)
    if language == "ru":
        text = f"Контекст миссии доступен. Дружественных контактов: {friendlies}, обнаруженных противников: {hostiles}, AWACS: {len(context.awacs)}, танкеров: {len(context.tankers)}, JTAC: {len(context.jtac)}."
    else:
        text = f"Mission context is available. Friendly contacts: {friendlies}, detected hostiles: {hostiles}, AWACS: {len(context.awacs)}, tankers: {len(context.tankers)}, JTAC: {len(context.jtac)}."
    return MissionContextVoiceResult(True, text, {"mission_id": context.mission_id, "friendlies": friendlies, "hostiles": hostiles, "awacs": len(context.awacs), "tankers": len(context.tankers), "jtac": len(context.jtac)})


def _support_list(assets: list[SupportAsset], label: str, language: str) -> MissionContextVoiceResult:
    available = [asset for asset in assets if asset.available]
    if not available:
        text = f"Доступные {label} в данных миссии не найдены." if language == "ru" else f"No available {label} were found in the mission data."
        return MissionContextVoiceResult(False, text, {"assets": []})
    parts = [_support_phrase(asset, language) for asset in available]
    prefix = f"Доступные {label}: " if language == "ru" else f"Available {label}: "
    return MissionContextVoiceResult(True, prefix + "; ".join(parts) + ".", {"assets": [asset.model_dump(mode="json") for asset in available]})


def _nearest_contact(contacts: list[MissionContact], *, hostile: bool, language: str) -> MissionContextVoiceResult:
    ranged = [contact for contact in contacts if contact.distance_km is not None and contact.bearing_deg is not None]
    if not ranged:
        target = "противник" if hostile else "дружественный контакт"
        text = f"Не могу определить ближайший {target}: нет контактов с рассчитанной дальностью." if language == "ru" else f"I cannot determine the nearest {'hostile' if hostile else 'friendly'} contact because no ranged contacts are available."
        return MissionContextVoiceResult(False, text, {"contacts": []})
    contact = min(ranged, key=lambda item: item.distance_km if item.distance_km is not None else float("inf"))
    if language == "ru":
        label = "Ближайший противник" if hostile else "Ближайший дружественный"
        text = f"{label}: {contact.name}, азимут {contact.bearing_deg:.0f}, дальность {contact.distance_km:.1f} километра, высота {contact.altitude_m:.0f} метров."
    else:
        label = "Nearest hostile" if hostile else "Nearest friendly"
        text = f"{label}: {contact.name}, bearing {contact.bearing_deg:.0f}, range {contact.distance_km:.1f} kilometers, altitude {contact.altitude_m:.0f} meters."
    return MissionContextVoiceResult(True, text, {"contact": contact.model_dump(mode="json")})


def _nearest_support(assets: list[SupportAsset], label: str, language: str) -> MissionContextVoiceResult:
    available = [asset for asset in assets if asset.available]
    if not available:
        text = f"Доступный {label} не найден." if language == "ru" else f"No available {label} was found."
        return MissionContextVoiceResult(False, text, {"assets": []})
    # Mission radio assets do not yet carry geodetic coordinates. Report the first available asset without inventing range.
    asset = available[0]
    if language == "ru":
        text = f"Доступен {label} {asset.callsign}."
        if asset.frequency_mhz is not None:
            text += f" Частота {asset.frequency_mhz:.3f} мегагерц{(' ' + asset.modulation) if asset.modulation else ''}."
        text += " Положение пока не передано Mission Bridge."
    else:
        text = f"Available {label}: {asset.callsign}."
        if asset.frequency_mhz is not None:
            text += f" Frequency {asset.frequency_mhz:.3f} megahertz{(' ' + asset.modulation) if asset.modulation else ''}."
        text += " Position is not yet provided by Mission Bridge."
    return MissionContextVoiceResult(True, text, {"asset": asset.model_dump(mode="json"), "position_available": False})


def _support_phrase(asset: SupportAsset, language: str) -> str:
    text = asset.callsign
    if asset.unit_type:
        text += f", {asset.unit_type}"
    if asset.frequency_mhz is not None:
        if language == "ru":
            text += f", {asset.frequency_mhz:.3f} мегагерц"
        else:
            text += f", {asset.frequency_mhz:.3f} megahertz"
        if asset.modulation:
            text += f" {asset.modulation}"
    return text


def _language(text: str) -> str:
    return "ru" if any("а" <= char.casefold() <= "я" or char.casefold() == "ё" for char in text) else "en"
