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
        return MissionContextVoiceResult(completed=False, spoken_text=text, data={"issues": context.issues})

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
    if intent in {"nearest_tanker", "find_tanker"}:
        return _nearest_support(context.tankers, "танкер" if language == "ru" else "tanker", language)
    if intent == "nearest_awacs":
        return _nearest_support(context.awacs, "AWACS", language)
    if intent == "request_tacan":
        return _tanker_tacan(context, language)
    if intent == "request_frequency":
        return _tanker_frequency(context, language)

    return MissionContextVoiceResult(completed=False, spoken_text="Этот запрос контекста миссии пока не поддерживается." if language == "ru" else "This mission-context query is not supported yet.")


def _summary(context: LiveMissionContext, language: str) -> MissionContextVoiceResult:
    friendlies = len(context.friendlies)
    hostiles = len(context.hostiles)
    if language == "ru":
        text = f"Контекст миссии доступен. Дружественных контактов: {friendlies}, обнаруженных противников: {hostiles}, AWACS: {len(context.awacs)}, танкеров: {len(context.tankers)}, JTAC: {len(context.jtac)}."
    else:
        text = f"Mission context is available. Friendly contacts: {friendlies}, detected hostiles: {hostiles}, AWACS: {len(context.awacs)}, tankers: {len(context.tankers)}, JTAC: {len(context.jtac)}."
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"mission_id": context.mission_id, "friendlies": friendlies, "hostiles": hostiles, "awacs": len(context.awacs), "tankers": len(context.tankers), "jtac": len(context.jtac)})


def _available_tankers(context: LiveMissionContext) -> list[SupportAsset]:
    return [asset for asset in context.tankers if asset.available and asset.aar_available is not False]


def _select_nearest(assets: list[SupportAsset]) -> SupportAsset | None:
    if not assets:
        return None
    ranged = [asset for asset in assets if asset.distance_km is not None]
    return min(ranged, key=lambda item: item.distance_km or 0) if ranged else assets[0]


def _tanker_tacan(context: LiveMissionContext, language: str) -> MissionContextVoiceResult:
    asset = _select_nearest(_available_tankers(context))
    if asset is None:
        text = "Доступный танкер не найден." if language == "ru" else "No available tanker was found."
        return MissionContextVoiceResult(completed=False, spoken_text=text)
    if asset.tacan_channel is None or asset.tacan_band is None:
        text = f"Для танкера {asset.callsign} TACAN не передан Mission Bridge." if language == "ru" else f"Mission Bridge has no TACAN data for tanker {asset.callsign}."
        return MissionContextVoiceResult(completed=False, spoken_text=text, data={"asset": asset.model_dump(mode="json")})
    text = f"Танкер {asset.callsign}, TACAN {asset.tacan_channel} {asset.tacan_band}." if language == "ru" else f"Tanker {asset.callsign}, TACAN {asset.tacan_channel} {asset.tacan_band}."
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"asset": asset.model_dump(mode="json")})


def _tanker_frequency(context: LiveMissionContext, language: str) -> MissionContextVoiceResult:
    asset = _select_nearest(_available_tankers(context))
    if asset is None:
        text = "Доступный танкер не найден." if language == "ru" else "No available tanker was found."
        return MissionContextVoiceResult(completed=False, spoken_text=text)
    if asset.frequency_mhz is None:
        text = f"Для танкера {asset.callsign} частота не передана Mission Bridge." if language == "ru" else f"Mission Bridge has no frequency for tanker {asset.callsign}."
        return MissionContextVoiceResult(completed=False, spoken_text=text, data={"asset": asset.model_dump(mode="json")})
    modulation = f" {asset.modulation}" if asset.modulation else ""
    text = f"Танкер {asset.callsign}, частота {asset.frequency_mhz:.3f} мегагерц{modulation}." if language == "ru" else f"Tanker {asset.callsign}, frequency {asset.frequency_mhz:.3f} megahertz{modulation}."
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"asset": asset.model_dump(mode="json")})


def _support_list(assets: list[SupportAsset], label: str, language: str) -> MissionContextVoiceResult:
    available = [asset for asset in assets if asset.available]
    if not available:
        text = f"Доступные {label} в данных миссии не найдены." if language == "ru" else f"No available {label} were found in the mission data."
        return MissionContextVoiceResult(completed=False, spoken_text=text, data={"assets": []})
    parts = [_support_phrase(asset, language) for asset in available]
    prefix = f"Доступные {label}: " if language == "ru" else f"Available {label}: "
    return MissionContextVoiceResult(completed=True, spoken_text=prefix + "; ".join(parts) + ".", data={"assets": [asset.model_dump(mode="json") for asset in available]})


def _nearest_contact(contacts: list[MissionContact], *, hostile: bool, language: str) -> MissionContextVoiceResult:
    ranged = [contact for contact in contacts if contact.distance_km is not None and contact.bearing_deg is not None]
    if not ranged:
        target = "противник" if hostile else "дружественный контакт"
        text = f"Не могу определить ближайший {target}: нет контактов с рассчитанной дальностью." if language == "ru" else f"I cannot determine the nearest {'hostile' if hostile else 'friendly'} contact because no ranged contacts are available."
        return MissionContextVoiceResult(completed=False, spoken_text=text, data={"contacts": []})
    contact = min(ranged, key=lambda item: item.distance_km if item.distance_km is not None else float("inf"))
    if language == "ru":
        label = "Ближайший противник" if hostile else "Ближайший дружественный"
        text = f"{label}: {contact.name}, азимут {contact.bearing_deg:.0f}, дальность {contact.distance_km:.1f} километра, высота {contact.altitude_m:.0f} метров."
    else:
        label = "Nearest hostile" if hostile else "Nearest friendly"
        text = f"{label}: {contact.name}, bearing {contact.bearing_deg:.0f}, range {contact.distance_km:.1f} kilometers, altitude {contact.altitude_m:.0f} meters."
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"contact": contact.model_dump(mode="json")})


def _nearest_support(assets: list[SupportAsset], label: str, language: str) -> MissionContextVoiceResult:
    available = [asset for asset in assets if asset.available and (asset.role.value != "tanker" or asset.aar_available is not False)]
    if not available:
        text = f"Доступный {label} не найден." if language == "ru" else f"No available {label} was found."
        return MissionContextVoiceResult(completed=False, spoken_text=text, data={"assets": []})
    asset = _select_nearest(available) or available[0]
    if language == "ru":
        text = f"Доступен {label} {asset.callsign}."
        if asset.bearing_deg is not None and asset.distance_km is not None:
            text += f" Азимут {asset.bearing_deg:.0f}, дальность {asset.distance_km:.1f} километра."
            if asset.altitude_m is not None:
                text += f" Высота {asset.altitude_m:.0f} метров."
        else:
            text += " Положение пока не передано Mission Bridge."
        if asset.heading_deg is not None:
            text += f" Курс {asset.heading_deg:.0f}."
        if asset.speed_mps is not None:
            text += f" Скорость {asset.speed_mps:.0f} метров в секунду."
        if asset.frequency_mhz is not None:
            text += f" Частота {asset.frequency_mhz:.3f} мегагерц{(' ' + asset.modulation) if asset.modulation else ''}."
        if asset.tacan_channel is not None and asset.tacan_band is not None:
            text += f" TACAN {asset.tacan_channel} {asset.tacan_band}."
        if asset.role.value == "tanker" and asset.aar_available is True:
            text += " Дозаправка доступна."
    else:
        text = f"Available {label}: {asset.callsign}."
        if asset.bearing_deg is not None and asset.distance_km is not None:
            text += f" Bearing {asset.bearing_deg:.0f}, range {asset.distance_km:.1f} kilometers."
            if asset.altitude_m is not None:
                text += f" Altitude {asset.altitude_m:.0f} meters."
        else:
            text += " Position is not yet provided by Mission Bridge."
        if asset.heading_deg is not None:
            text += f" Heading {asset.heading_deg:.0f}."
        if asset.speed_mps is not None:
            text += f" Speed {asset.speed_mps:.0f} meters per second."
        if asset.frequency_mhz is not None:
            text += f" Frequency {asset.frequency_mhz:.3f} megahertz{(' ' + asset.modulation) if asset.modulation else ''}."
        if asset.tacan_channel is not None and asset.tacan_band is not None:
            text += f" TACAN {asset.tacan_channel} {asset.tacan_band}."
        if asset.role.value == "tanker" and asset.aar_available is True:
            text += " Aerial refueling is available."
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"asset": asset.model_dump(mode="json"), "position_available": asset.distance_km is not None and asset.bearing_deg is not None})


def _support_phrase(asset: SupportAsset, language: str) -> str:
    text = asset.callsign
    if asset.unit_type:
        text += f", {asset.unit_type}"
    if asset.bearing_deg is not None and asset.distance_km is not None:
        text += f", {'азимут' if language == 'ru' else 'bearing'} {asset.bearing_deg:.0f}, {asset.distance_km:.1f} {'километра' if language == 'ru' else 'kilometers'}"
    if asset.frequency_mhz is not None:
        text += f", {asset.frequency_mhz:.3f} {'мегагерц' if language == 'ru' else 'megahertz'}"
        if asset.modulation:
            text += f" {asset.modulation}"
    if asset.tacan_channel is not None and asset.tacan_band is not None:
        text += f", TACAN {asset.tacan_channel} {asset.tacan_band}"
    return text


def _language(text: str) -> str:
    return "ru" if any("а" <= char.casefold() <= "я" or char.casefold() == "ё" for char in text) else "en"
