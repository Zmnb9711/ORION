from __future__ import annotations

from math import atan2, cos, degrees, radians, sin, sqrt

from pydantic import BaseModel, Field

from orion.coalition_units import spoken_distance, spoken_speed
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
    if intent == "mission_context_summary": return _summary(context, language)
    if intent == "list_awacs": return _support_list(context.awacs, "AWACS", language)
    if intent == "list_tankers": return _support_list(context.tankers, "танкеры" if language == "ru" else "tankers", language)
    if intent == "list_jtac": return _support_list(context.jtac, "JTAC", language)
    if intent == "nearest_hostile": return _nearest_contact(context.hostiles, hostile=True, language=language)
    if intent == "nearest_friendly": return _nearest_contact(context.friendlies, hostile=False, language=language)
    if intent in {"nearest_tanker", "find_tanker"}: return _nearest_support(context.tankers, "танкер" if language == "ru" else "tanker", language, context)
    if intent == "nearest_awacs": return _nearest_support(context.awacs, "AWACS", language, context)
    if intent == "request_tacan": return _tanker_tacan(context, language)
    if intent == "request_frequency": return _tanker_frequency(context, language)
    return MissionContextVoiceResult(completed=False, spoken_text="Этот запрос контекста миссии пока не поддерживается." if language == "ru" else "This mission-context query is not supported yet.")


def _summary(context: LiveMissionContext, language: str) -> MissionContextVoiceResult:
    friendlies, hostiles = len(context.friendlies), len(context.hostiles)
    text = (f"Контекст миссии доступен. Дружественных контактов: {friendlies}, обнаруженных противников: {hostiles}, AWACS: {len(context.awacs)}, танкеров: {len(context.tankers)}, JTAC: {len(context.jtac)}." if language == "ru" else f"Mission context is available. Friendly contacts: {friendlies}, detected hostiles: {hostiles}, AWACS: {len(context.awacs)}, tankers: {len(context.tankers)}, JTAC: {len(context.jtac)}.")
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"mission_id": context.mission_id, "friendlies": friendlies, "hostiles": hostiles, "awacs": len(context.awacs), "tankers": len(context.tankers), "jtac": len(context.jtac)})


def _available_tankers(context: LiveMissionContext) -> list[SupportAsset]: return [a for a in context.tankers if a.available and a.aar_available is not False]

def _select_nearest(assets: list[SupportAsset]) -> SupportAsset | None:
    if not assets: return None
    ranged = [a for a in assets if a.distance_km is not None]
    return min(ranged, key=lambda a: a.distance_km or 0) if ranged else assets[0]


def _tanker_tacan(context: LiveMissionContext, language: str) -> MissionContextVoiceResult:
    asset = _select_nearest(_available_tankers(context))
    if asset is None: return MissionContextVoiceResult(completed=False, spoken_text="Доступный танкер не найден." if language == "ru" else "No available tanker was found.")
    if asset.tacan_channel is None or asset.tacan_band is None:
        text = f"Для танкера {asset.callsign} TACAN не передан Mission Bridge." if language == "ru" else f"Mission Bridge has no TACAN data for tanker {asset.callsign}."
        return MissionContextVoiceResult(completed=False, spoken_text=text, data={"asset": asset.model_dump(mode="json")})
    text = f"Танкер {asset.callsign}, TACAN {asset.tacan_channel} {asset.tacan_band}." if language == "ru" else f"Tanker {asset.callsign}, TACAN {asset.tacan_channel} {asset.tacan_band}."
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"asset": asset.model_dump(mode="json")})


def _tanker_frequency(context: LiveMissionContext, language: str) -> MissionContextVoiceResult:
    asset = _select_nearest(_available_tankers(context))
    if asset is None: return MissionContextVoiceResult(completed=False, spoken_text="Доступный танкер не найден." if language == "ru" else "No available tanker was found.")
    if asset.frequency_mhz is None:
        text = f"Для танкера {asset.callsign} частота не передана Mission Bridge." if language == "ru" else f"Mission Bridge has no frequency for tanker {asset.callsign}."
        return MissionContextVoiceResult(completed=False, spoken_text=text, data={"asset": asset.model_dump(mode="json")})
    modulation = f" {asset.modulation}" if asset.modulation else ""
    text = f"Танкер {asset.callsign}, частота {asset.frequency_mhz:.3f} мегагерц{modulation}." if language == "ru" else f"Tanker {asset.callsign}, frequency {asset.frequency_mhz:.3f} megahertz{modulation}."
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"asset": asset.model_dump(mode="json")})


def _support_list(assets: list[SupportAsset], label: str, language: str) -> MissionContextVoiceResult:
    available = [a for a in assets if a.available]
    if not available:
        return MissionContextVoiceResult(completed=False, spoken_text=f"Доступные {label} в данных миссии не найдены." if language == "ru" else f"No available {label} were found in the mission data.", data={"assets": []})
    prefix = f"Доступные {label}: " if language == "ru" else f"Available {label}: "
    return MissionContextVoiceResult(completed=True, spoken_text=prefix + "; ".join(_support_phrase(a, language) for a in available) + ".", data={"assets": [a.model_dump(mode="json") for a in available]})


def _nearest_contact(contacts: list[MissionContact], *, hostile: bool, language: str) -> MissionContextVoiceResult:
    ranged = [c for c in contacts if c.distance_km is not None and c.bearing_deg is not None]
    if not ranged:
        target = "противник" if hostile else "дружественный контакт"
        return MissionContextVoiceResult(completed=False, spoken_text=f"Не могу определить ближайший {target}: нет контактов с рассчитанной дальностью." if language == "ru" else f"I cannot determine the nearest {'hostile' if hostile else 'friendly'} contact because no ranged contacts are available.", data={"contacts": []})
    c = min(ranged, key=lambda x: x.distance_km if x.distance_km is not None else float("inf"))
    label = ("Ближайший противник" if hostile else "Ближайший дружественный") if language == "ru" else ("Nearest hostile" if hostile else "Nearest friendly")
    range_text = spoken_distance(c.distance_km, c.coalition, language)
    text = f"{label}: {c.name}, азимут {c.bearing_deg:.0f}, дальность {range_text}, высота {c.altitude_m:.0f} метров." if language == "ru" else f"{label}: {c.name}, bearing {c.bearing_deg:.0f}, range {range_text}, altitude {c.altitude_m:.0f} meters."
    if c.speed_mps is not None:
        text += f" {'Скорость' if language == 'ru' else 'Speed'} {spoken_speed(c.speed_mps, c.coalition, language)}."
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"contact": c.model_dump(mode="json")})


def _intercept_guidance(context: LiveMissionContext, asset: SupportAsset) -> dict[str, float] | None:
    own = context.ownship
    if own is None or own.true_airspeed_mps is None or own.true_airspeed_mps <= 0 or asset.latitude is None or asset.longitude is None or asset.heading_deg is None or asset.speed_mps is None:
        return None
    lat0 = radians(own.latitude)
    north = radians(asset.latitude - own.latitude) * 6371008.8
    east = radians(asset.longitude - own.longitude) * 6371008.8 * cos(lat0)
    h = radians(asset.heading_deg)
    ve, vn = asset.speed_mps * sin(h), asset.speed_mps * cos(h)
    s = own.true_airspeed_mps
    a = ve * ve + vn * vn - s * s
    b = 2.0 * (east * ve + north * vn)
    c = east * east + north * north
    if c < 1.0: return {"intercept_heading_deg": own.heading_deg or 0.0, "eta_s": 0.0, "intercept_distance_km": 0.0}
    roots: list[float] = []
    if abs(a) < 1e-9:
        if abs(b) > 1e-9: roots = [-c / b]
    else:
        d = b * b - 4 * a * c
        if d >= 0:
            q = sqrt(d)
            roots = [(-b - q) / (2 * a), (-b + q) / (2 * a)]
    positive = [t for t in roots if t > 0]
    if not positive: return None
    t = min(positive)
    ie, inn = east + ve * t, north + vn * t
    heading = (degrees(atan2(ie, inn)) + 360.0) % 360.0
    return {"intercept_heading_deg": round(heading, 1), "eta_s": round(t, 1), "intercept_distance_km": round(s * t / 1000.0, 1)}


def _nearest_support(assets: list[SupportAsset], label: str, language: str, context: LiveMissionContext) -> MissionContextVoiceResult:
    available = [a for a in assets if a.available and (a.role.value != "tanker" or a.aar_available is not False)]
    if not available: return MissionContextVoiceResult(completed=False, spoken_text=f"Доступный {label} не найден." if language == "ru" else f"No available {label} was found.", data={"assets": []})
    a = _select_nearest(available) or available[0]
    text = f"Доступен {label} {a.callsign}." if language == "ru" else f"Available {label}: {a.callsign}."
    if a.bearing_deg is not None and a.distance_km is not None:
        text += (f" Азимут {a.bearing_deg:.0f}, дальность {spoken_distance(a.distance_km, a.coalition, language)}." if language == "ru" else f" Bearing {a.bearing_deg:.0f}, range {spoken_distance(a.distance_km, a.coalition, language)}.")
        if a.altitude_m is not None: text += f" {'Высота' if language == 'ru' else 'Altitude'} {a.altitude_m:.0f} {'метров' if language == 'ru' else 'meters'}."
    else: text += " Положение пока не передано Mission Bridge." if language == "ru" else " Position is not yet provided by Mission Bridge."
    if a.heading_deg is not None: text += f" {'Курс' if language == 'ru' else 'Heading'} {a.heading_deg:.0f}."
    if a.speed_mps is not None: text += f" {'Скорость' if language == 'ru' else 'Speed'} {spoken_speed(a.speed_mps, a.coalition, language)}."
    if a.frequency_mhz is not None: text += f" {'Частота' if language == 'ru' else 'Frequency'} {a.frequency_mhz:.3f} {'мегагерц' if language == 'ru' else 'megahertz'}{(' ' + a.modulation) if a.modulation else ''}."
    if a.tacan_channel is not None and a.tacan_band is not None: text += f" TACAN {a.tacan_channel} {a.tacan_band}."
    guidance = _intercept_guidance(context, a) if a.role.value == "tanker" else None
    if guidance:
        minutes = guidance["eta_s"] / 60.0
        distance_text = spoken_distance(guidance["intercept_distance_km"], a.coalition, language)
        text += (f" Рекомендуемый курс перехвата {guidance['intercept_heading_deg']:.0f}, расчетное время встречи {minutes:.1f} минуты, путь до точки встречи {distance_text}." if language == "ru" else f" Recommended intercept heading {guidance['intercept_heading_deg']:.0f}, estimated rendezvous time {minutes:.1f} minutes, distance to rendezvous {distance_text}.")
    if a.role.value == "tanker" and a.aar_available is True: text += " Дозаправка доступна." if language == "ru" else " Aerial refueling is available."
    return MissionContextVoiceResult(completed=True, spoken_text=text, data={"asset": a.model_dump(mode="json"), "position_available": a.distance_km is not None and a.bearing_deg is not None, "intercept_guidance": guidance})


def _support_phrase(asset: SupportAsset, language: str) -> str:
    text = asset.callsign
    if asset.unit_type: text += f", {asset.unit_type}"
    if asset.bearing_deg is not None and asset.distance_km is not None: text += f", {'азимут' if language == 'ru' else 'bearing'} {asset.bearing_deg:.0f}, {spoken_distance(asset.distance_km, asset.coalition, language)}"
    if asset.speed_mps is not None: text += f", {spoken_speed(asset.speed_mps, asset.coalition, language)}"
    if asset.frequency_mhz is not None:
        text += f", {asset.frequency_mhz:.3f} {'мегагерц' if language == 'ru' else 'megahertz'}"
        if asset.modulation: text += f" {asset.modulation}"
    if asset.tacan_channel is not None and asset.tacan_band is not None: text += f", TACAN {asset.tacan_channel} {asset.tacan_band}"
    return text


def _language(text: str) -> str: return "ru" if any("а" <= c.casefold() <= "я" or c.casefold() == "ё" for c in text) else "en"
