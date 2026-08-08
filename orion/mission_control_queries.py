from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.mission_control_runtime import MissionControlPicture, build_mission_control_picture
from orion.tactical_situation import TacticalThreat, TacticalThreatKind
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, voice_commands


class MissionControlQueryKind(StrEnum):
    PICTURE = "picture"
    PRIMARY_THREAT = "primary_threat"
    CLOCK_SECTOR = "clock_sector"


class MissionControlQuery(BaseModel):
    kind: MissionControlQueryKind
    clock_hour: int | None = Field(default=None, ge=1, le=12)
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

    if query.kind is MissionControlQueryKind.PICTURE:
        threats = _picture_threats(picture)
        text = _picture_text(picture, ru)
        return _result(text, threats, query, VoiceAgent.AWACS)

    if query.kind is MissionControlQueryKind.PRIMARY_THREAT:
        threat = picture.primary_air_threat or picture.primary_surface_threat
        if threat is None:
            text = "Приоритетных угроз нет." if ru else "No prioritized threats."
            return _result(text, [], query, VoiceAgent.AWACS)
        text = _threat_text(threat, ru, primary=True)
        agent = VoiceAgent.AWACS if threat.kind is TacticalThreatKind.AIR else VoiceAgent.MISSION_CONTROL
        return _result(text, [threat], query, agent)

    assert query.clock_hour is not None
    threats = _threats_in_clock_sector(picture, query.clock_hour)
    if not threats:
        text = (
            f"На {query.clock_hour} часов приоритетных угроз нет."
            if ru
            else f"No prioritized threats at {query.clock_hour} o'clock."
        )
        return _result(text, [], query, VoiceAgent.AWACS)

    lead = threats[0]
    text = (
        f"На {query.clock_hour} часов: {_threat_text(lead, ru, primary=False)}"
        if ru
        else f"At {query.clock_hour} o'clock: {_threat_text(lead, ru, primary=False)}"
    )
    return _result(text, threats, query, VoiceAgent.AWACS if lead.kind is TacticalThreatKind.AIR else VoiceAgent.MISSION_CONTROL)


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
    if ru:
        return f"{lead} Дополнительных приоритетных контактов: {len(items) - 1}."
    return f"{lead} Additional prioritized contacts: {len(items) - 1}."


def _threat_text(threat: TacticalThreat, ru: bool, *, primary: bool) -> str:
    if threat.kind is TacticalThreatKind.AIR:
        prefix = "Главная воздушная угроза" if ru and primary else "Воздушная угроза" if ru else "Primary air threat" if primary else "Air threat"
        return f"{prefix}, {threat.braa}, уровень {threat.level.value}." if ru else f"{prefix}, {threat.braa}, level {threat.level.value}."
    prefix = "Главная наземная угроза" if ru and primary else "Наземная угроза" if ru else "Primary surface threat" if primary else "Surface threat"
    if ru:
        return f"{prefix}, азимут {threat.bearing_deg:.0f}, дальность {threat.range_nm:.0f} морских миль, уровень {threat.level.value}."
    return f"{prefix}, bearing {threat.bearing_deg:.0f}, range {threat.range_nm:.0f} nautical miles, level {threat.level.value}."


def _threats_in_clock_sector(picture: MissionControlPicture, hour: int) -> list[TacticalThreat]:
    center = (hour % 12) * 30.0
    candidates = _picture_threats(picture)
    return [item for item in candidates if _angular_difference(item.bearing_deg, center) <= 15.0]


def _angular_difference(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)
