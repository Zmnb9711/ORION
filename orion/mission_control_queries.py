from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.live_telemetry_store import live_telemetry
from orion.mission_control_runtime import MissionControlPicture, build_mission_control_picture
from orion.tactical_situation import TacticalThreat, TacticalThreatKind
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, voice_commands


class MissionControlQueryKind(StrEnum):
    PICTURE = "picture"
    PRIMARY_THREAT = "primary_threat"
    CLOSEST_THREAT = "closest_threat"
    MOST_DANGEROUS = "most_dangerous"
    CLOCK_SECTOR = "clock_sector"
    RELATIVE_SECTOR = "relative_sector"
    SAM_AHEAD = "sam_ahead"


class RelativeSector(StrEnum):
    AHEAD = "ahead"
    LEFT = "left"
    RIGHT = "right"


class MissionControlQuery(BaseModel):
    kind: MissionControlQueryKind
    clock_hour: int | None = Field(default=None, ge=1, le=12)
    sector: RelativeSector | None = None
    language: str = "en"
    speak: bool = False


class MissionControlQueryResult(BaseModel):
    available: bool
    text: str
    threats: list[TacticalThreat] = Field(default_factory=list)
    voice_command: VoiceCommand | None = None


def execute_mission_control_query(query: MissionControlQuery) -> MissionControlQueryResult:
    picture = build_mission_control_picture()
    ru = query.language.casefold().startswith("ru")

    if picture.readiness.value == "unavailable":
        text = "Тактическая обстановка недоступна." if ru else "Tactical picture unavailable."
        return _result(text, [], query, VoiceAgent.MISSION_CONTROL)

    threats = _picture_threats(picture)

    if query.kind is MissionControlQueryKind.PICTURE:
        return _result(_picture_text(picture, ru), threats, query, VoiceAgent.AWACS)

    if query.kind is MissionControlQueryKind.PRIMARY_THREAT:
        threat = picture.primary_air_threat or picture.primary_surface_threat
        return _single_threat_result(threat, query, ru, "Приоритетных угроз нет.", "No prioritized threats.")

    if query.kind is MissionControlQueryKind.CLOSEST_THREAT:
        threat = min(threats, key=lambda item: item.range_nm, default=None)
        return _single_threat_result(threat, query, ru, "Угроз поблизости нет.", "No nearby prioritized threats.", label="closest")

    if query.kind is MissionControlQueryKind.MOST_DANGEROUS:
        threat = max(threats, key=lambda item: (item.tactical_priority, item.score), default=None)
        return _single_threat_result(threat, query, ru, "Приоритетных угроз нет.", "No prioritized threats.", label="dangerous")

    heading = _own_heading_deg()
    if heading is None:
        text = "Курс самолёта недоступен." if ru else "Ownship heading unavailable."
        return _result(text, [], query, VoiceAgent.MISSION_CONTROL)

    if query.kind is MissionControlQueryKind.CLOCK_SECTOR:
        assert query.clock_hour is not None
        selected = _threats_in_clock_sector(threats, query.clock_hour, heading)
        if not selected:
            text = f"На {query.clock_hour} часов приоритетных угроз нет." if ru else f"No prioritized threats at {query.clock_hour} o'clock."
            return _result(text, [], query, VoiceAgent.AWACS)
        lead = selected[0]
        text = f"На {query.clock_hour} часов: {_threat_text(lead, ru, primary=False)}" if ru else f"At {query.clock_hour} o'clock: {_threat_text(lead, ru, primary=False)}"
        return _result(text, selected, query, _agent_for(lead))

    if query.kind is MissionControlQueryKind.RELATIVE_SECTOR:
        assert query.sector is not None
        selected = _threats_in_relative_sector(threats, query.sector, heading)
        label_ru = {RelativeSector.AHEAD: "впереди", RelativeSector.LEFT: "слева", RelativeSector.RIGHT: "справа"}[query.sector]
        label_en = query.sector.value
        if not selected:
            text = f"Приоритетных угроз {label_ru} нет." if ru else f"No prioritized threats {label_en}."
            return _result(text, [], query, VoiceAgent.AWACS)
        lead = selected[0]
        text = f"{label_ru.capitalize()}: {_threat_text(lead, ru, primary=False)}" if ru else f"{label_en.capitalize()}: {_threat_text(lead, ru, primary=False)}"
        return _result(text, selected, query, _agent_for(lead))

    assert query.kind is MissionControlQueryKind.SAM_AHEAD
    selected = [
        item for item in threats
        if item.kind is TacticalThreatKind.SAM and _angular_difference(item.bearing_deg, heading) <= 30.0
    ]
    selected.sort(key=lambda item: (item.range_nm, -item.tactical_priority))
    if not selected:
        text = "ПВО впереди по текущему курсу не обнаружено." if ru else "No prioritized SAM threat ahead on current heading."
        return _result(text, [], query, VoiceAgent.MISSION_CONTROL)
    lead = selected[0]
    text = f"ПВО впереди: {_threat_text(lead, ru, primary=False)}" if ru else f"SAM ahead: {_threat_text(lead, ru, primary=False)}"
    return _result(text, selected, query, VoiceAgent.MISSION_CONTROL)


def _single_threat_result(threat: TacticalThreat | None, query: MissionControlQuery, ru: bool, empty_ru: str, empty_en: str, label: str | None = None) -> MissionControlQueryResult:
    if threat is None:
        return _result(empty_ru if ru else empty_en, [], query, VoiceAgent.AWACS)
    if label == "closest":
        prefix = "Ближайшая угроза" if ru else "Closest threat"
        text = f"{prefix}: {_threat_text(threat, ru, primary=False)}"
    elif label == "dangerous":
        prefix = "Наиболее опасная угроза" if ru else "Most dangerous threat"
        text = f"{prefix}: {_threat_text(threat, ru, primary=False)}"
    else:
        text = _threat_text(threat, ru, primary=True)
    return _result(text, [threat], query, _agent_for(threat))


def _result(text: str, threats: list[TacticalThreat], query: MissionControlQuery, agent: VoiceAgent) -> MissionControlQueryResult:
    command = None
    if query.speak:
        command = voice_commands.submit(
            VoiceCommandCreate(
                transcript=text,
                intent=f"mission_control_{query.kind.value}",
                agent=agent,
                priority=CommandPriority.HIGH if threats else CommandPriority.NORMAL,
                context={
                    "query_kind": query.kind.value,
                    "threat_count": len(threats),
                    "clock_hour": query.clock_hour,
                    "sector": query.sector.value if query.sector else None,
                },
            )
        )
    return MissionControlQueryResult(available=True, text=text, threats=threats, voice_command=command)


def _picture_threats(picture: MissionControlPicture) -> list[TacticalThreat]:
    items: list[TacticalThreat] = []
    if picture.primary_air_threat is not None:
        items.append(picture.primary_air_threat)
    items.extend(picture.secondary_air_threats)
    if picture.primary_surface_threat is not None:
        items.append(picture.primary_surface_threat)
    return items


def _picture_text(picture: MissionControlPicture, ru: bool) -> str:
    items = _picture_threats(picture)
    if not items:
        return "Приоритетных угроз нет." if ru else "No prioritized threats."
    lead = _threat_text(items[0], ru, primary=True)
    if len(items) == 1:
        return lead
    return f"{lead} Дополнительных приоритетных контактов: {len(items) - 1}." if ru else f"{lead} Additional prioritized contacts: {len(items) - 1}."


def _threat_text(threat: TacticalThreat, ru: bool, *, primary: bool) -> str:
    if threat.kind is TacticalThreatKind.AIR:
        prefix = "Главная воздушная угроза" if ru and primary else "Воздушная угроза" if ru else "Primary air threat" if primary else "Air threat"
        return f"{prefix}, {threat.braa}, уровень {threat.level.value}." if ru else f"{prefix}, {threat.braa}, level {threat.level.value}."
    prefix = "Главная наземная угроза" if ru and primary else "Наземная угроза" if ru else "Primary surface threat" if primary else "Surface threat"
    if ru:
        return f"{prefix}, азимут {threat.bearing_deg:.0f}, дальность {threat.range_nm:.0f} морских миль, уровень {threat.level.value}."
    return f"{prefix}, bearing {threat.bearing_deg:.0f}, range {threat.range_nm:.0f} nautical miles, level {threat.level.value}."


def _own_heading_deg() -> float | None:
    telemetry = live_telemetry.get()
    return telemetry.state.heading_deg if telemetry is not None else None


def _threats_in_clock_sector(threats: list[TacticalThreat], hour: int, heading_deg: float) -> list[TacticalThreat]:
    relative_center = (hour % 12) * 30.0
    absolute_center = (heading_deg + relative_center) % 360.0
    return [item for item in threats if _angular_difference(item.bearing_deg, absolute_center) <= 15.0]


def _threats_in_relative_sector(threats: list[TacticalThreat], sector: RelativeSector, heading_deg: float) -> list[TacticalThreat]:
    center = {
        RelativeSector.AHEAD: heading_deg,
        RelativeSector.LEFT: (heading_deg - 90.0) % 360.0,
        RelativeSector.RIGHT: (heading_deg + 90.0) % 360.0,
    }[sector]
    return [item for item in threats if _angular_difference(item.bearing_deg, center) <= 45.0]


def _agent_for(threat: TacticalThreat) -> VoiceAgent:
    return VoiceAgent.AWACS if threat.kind is TacticalThreatKind.AIR else VoiceAgent.MISSION_CONTROL


def _angular_difference(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)
