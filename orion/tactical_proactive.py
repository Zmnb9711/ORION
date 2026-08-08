from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from orion.awacs_briefing import build_awacs_briefing
from orion.tactical_situation import TacticalThreat, TacticalThreatKind, get_tactical_situation
from orion.threats import ThreatLevel
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, voice_commands


@dataclass(frozen=True)
class _ThreatMemory:
    level: ThreatLevel
    range_nm: float


class TacticalProactiveMonitor:
    """Emit sparse tactical voice callouts only for meaningful threat changes."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._seen: dict[str, _ThreatMemory] = {}

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()

    def poll(self, language: str = "en") -> list[VoiceCommand]:
        summary = get_tactical_situation(limit=5)
        if not summary.available:
            return []

        briefing = build_awacs_briefing(summary.priority_threats, max_secondary=2)
        air_contacts = []
        if briefing.primary is not None:
            air_contacts.append((briefing.primary, True, 0))
            air_contacts.extend((item, False, index + 1) for index, item in enumerate(briefing.secondary))
        non_air = [item for item in summary.priority_threats if item.kind is not TacticalThreatKind.AIR]

        commands: list[VoiceCommand] = []
        current_ids = {item.unit_id for item, _, _ in air_contacts} | {item.unit_id for item in non_air}
        with self._lock:
            for threat, is_primary, secondary_rank in air_contacts:
                previous = self._seen.get(threat.unit_id)
                if not _meaningful_change(threat, previous):
                    self._seen[threat.unit_id] = _ThreatMemory(threat.level, threat.range_nm)
                    continue
                command = voice_commands.submit(
                    VoiceCommandCreate(
                        transcript=_awacs_callout(threat, language, primary=is_primary),
                        intent="tactical_threat_callout",
                        agent=VoiceAgent.AWACS,
                        priority=_priority(threat.level) if is_primary else _secondary_priority(threat.level),
                        context=_context(threat, awacs_primary=is_primary, secondary_rank=secondary_rank),
                    )
                )
                commands.append(command)
                self._seen[threat.unit_id] = _ThreatMemory(threat.level, threat.range_nm)

            for threat in non_air:
                previous = self._seen.get(threat.unit_id)
                if not _meaningful_change(threat, previous):
                    self._seen[threat.unit_id] = _ThreatMemory(threat.level, threat.range_nm)
                    continue
                command = voice_commands.submit(
                    VoiceCommandCreate(
                        transcript=_callout(threat, language),
                        intent="tactical_threat_callout",
                        agent=VoiceAgent.MISSION_CONTROL,
                        priority=_priority(threat.level),
                        context=_context(threat),
                    )
                )
                commands.append(command)
                self._seen[threat.unit_id] = _ThreatMemory(threat.level, threat.range_nm)

            for stale_id in list(self._seen):
                if stale_id not in current_ids:
                    del self._seen[stale_id]
        return commands


def _context(threat: TacticalThreat, awacs_primary: bool = False, secondary_rank: int = 0) -> dict[str, str | int | float | bool | None]:
    return {
        "unit_id": threat.unit_id,
        "kind": threat.kind.value,
        "threat_level": threat.level.value,
        "range_nm": threat.range_nm,
        "bearing_deg": threat.bearing_deg,
        "braa": threat.braa,
        "aspect": threat.kinematics.aspect.value,
        "range_trend": threat.kinematics.range_trend.value,
        "closure_kts": threat.kinematics.closure_kts,
        "tactical_priority": threat.tactical_priority,
        "awacs_primary": awacs_primary,
        "awacs_secondary_rank": secondary_rank,
    }


def _meaningful_change(threat: TacticalThreat, previous: _ThreatMemory | None) -> bool:
    if threat.level not in {ThreatLevel.HIGH, ThreatLevel.CRITICAL}:
        return False
    if previous is None:
        return True
    if _severity(threat.level) > _severity(previous.level):
        return True
    return previous.range_nm - threat.range_nm >= 10.0


def _severity(level: ThreatLevel) -> int:
    return {
        ThreatLevel.LOW: 0,
        ThreatLevel.MEDIUM: 1,
        ThreatLevel.HIGH: 2,
        ThreatLevel.CRITICAL: 3,
    }[level]


def _priority(level: ThreatLevel) -> CommandPriority:
    return CommandPriority.CRITICAL if level is ThreatLevel.CRITICAL else CommandPriority.HIGH


def _secondary_priority(level: ThreatLevel) -> CommandPriority:
    return CommandPriority.HIGH if level is ThreatLevel.CRITICAL else CommandPriority.NORMAL


def _air_kinematics(threat: TacticalThreat, ru: bool) -> str:
    aspect = threat.kinematics.aspect.value
    trend = threat.kinematics.range_trend.value
    closure = threat.kinematics.closure_kts
    if ru:
        aspect_text = {"hot": "идёт навстречу", "flanking": "фланговый", "cold": "уходит", "unknown": "аспект неизвестен"}[aspect]
        trend_text = {"closing": "сближается", "stable": "дальность стабильна", "diverging": "расходится", "unknown": "тренд неизвестен"}[trend]
        if closure is not None and trend == "closing":
            closure_kmh = abs(closure) * 1.852
            return f"{aspect_text}, {trend_text}, скорость сближения {closure_kmh:.0f} километров в час"
        return f"{aspect_text}, {trend_text}"
    aspect_text = {"hot": "hot", "flanking": "flanking", "cold": "cold", "unknown": "aspect unknown"}[aspect]
    trend_text = {"closing": "closing", "stable": "range stable", "diverging": "diverging", "unknown": "trend unknown"}[trend]
    if closure is not None and trend == "closing":
        return f"{aspect_text}, {trend_text}, closure {abs(closure):.0f} knots"
    return f"{aspect_text}, {trend_text}"


def _short_aspect(threat: TacticalThreat, ru: bool) -> str:
    aspect = threat.kinematics.aspect.value
    trend = threat.kinematics.range_trend.value
    if ru:
        aspect_text = {"hot": "навстречу", "flanking": "фланговый", "cold": "уходит", "unknown": "аспект неизвестен"}[aspect]
        trend_text = {"closing": "сближается", "stable": "дальность стабильна", "diverging": "удаляется", "unknown": ""}[trend]
    else:
        aspect_text = {"hot": "hot", "flanking": "flanking", "cold": "cold", "unknown": "aspect unknown"}[aspect]
        trend_text = {"closing": "closing", "stable": "range stable", "diverging": "diverging", "unknown": ""}[trend]
    return ", ".join(part for part in (aspect_text, trend_text) if part)


def _awacs_callout(threat: TacticalThreat, language: str, primary: bool) -> str:
    ru = language.casefold().startswith("ru")
    if primary:
        kin = _air_kinematics(threat, ru)
        return (
            f"Главная воздушная угроза, {threat.braa}. {kin}. Уровень {threat.level.value}."
            if ru
            else f"Primary air threat, {threat.braa}. {kin}. Threat level {threat.level.value}."
        )
    short = _short_aspect(threat, ru)
    return (
        f"Вторичный контакт, {threat.braa}. {short}."
        if ru
        else f"Secondary contact, {threat.braa}. {short}."
    )


def _callout(threat: TacticalThreat, language: str) -> str:
    ru = language.casefold().startswith("ru")
    if threat.kind is TacticalThreatKind.AIR:
        return _awacs_callout(threat, language, primary=True)
    if threat.kind is TacticalThreatKind.SAM:
        return (
            f"Угроза ПВО, азимут {threat.bearing_deg:.0f}, дальность {threat.range_nm:.0f} морских миль. Уровень {threat.level.value}."
            if ru
            else f"SAM threat, bearing {threat.bearing_deg:.0f}, range {threat.range_nm:.0f} nautical miles. Threat level {threat.level.value}."
        )
    return (
        f"Тактическая угроза, азимут {threat.bearing_deg:.0f}, дальность {threat.range_nm:.0f} морских миль."
        if ru
        else f"Tactical threat, bearing {threat.bearing_deg:.0f}, range {threat.range_nm:.0f} nautical miles."
    )


tactical_proactive = TacticalProactiveMonitor()
