from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.live_telemetry_store import live_telemetry
from orion.mission import Coalition, MissionPosition, UnitCategory
from orion.mission_store import mission_store
from orion.tactical_kinematics import ThreatKinematics, assess_threat_kinematics
from orion.threats import ThreatAssessment, ThreatLevel, assess_threats


class TacticalThreatKind(StrEnum):
    AIR = "air"
    SAM = "sam"
    GROUND = "ground"
    NAVAL = "naval"
    UNKNOWN = "unknown"


class DefensiveRecommendation(StrEnum):
    MONITOR = "monitor"
    INCREASE_SEPARATION = "increase_separation"
    DEFENSIVE = "defensive"
    BREAK_CONTACT = "break_contact"


class TacticalThreat(BaseModel):
    unit_id: str
    name: str
    type_name: str | None = None
    kind: TacticalThreatKind
    level: ThreatLevel
    score: float = Field(ge=0, le=100)
    bearing_deg: float = Field(ge=0, lt=360)
    range_nm: float = Field(ge=0)
    altitude_ft: int | None = None
    braa: str
    reasons: list[str] = Field(default_factory=list)
    kinematics: ThreatKinematics = Field(default_factory=ThreatKinematics)
    tactical_priority: float = Field(default=0, ge=0, le=100)


class TacticalSituationSummary(BaseModel):
    available: bool = False
    overall_level: ThreatLevel = ThreatLevel.LOW
    recommendation: DefensiveRecommendation = DefensiveRecommendation.MONITOR
    total_threats: int = 0
    air_threats: int = 0
    sam_threats: int = 0
    highest_priority: TacticalThreat | None = None
    priority_threats: list[TacticalThreat] = Field(default_factory=list)


def get_tactical_situation(limit: int = 5) -> TacticalSituationSummary:
    snapshot = mission_store.get()
    telemetry = live_telemetry.get()
    if snapshot is None or telemetry is None:
        return TacticalSituationSummary()

    own_position = MissionPosition(
        latitude=telemetry.state.position.latitude,
        longitude=telemetry.state.position.longitude,
        altitude_m=telemetry.state.position.altitude_m,
    )
    assessments = assess_threats(snapshot, own_position, own_coalition=Coalition.BLUE)
    units = {unit.unit_id: unit for unit in snapshot.units}

    tactical: list[TacticalThreat] = []
    for assessment in assessments:
        unit = units.get(assessment.unit_id)
        kind = _kind(unit.category if unit else UnitCategory.UNKNOWN, unit.type_name if unit else None)
        altitude_ft = round(unit.position.altitude_m * 3.28084) if unit else None
        range_nm = assessment.distance_m / 1852.0
        kinematics = assess_threat_kinematics(unit, own_position) if unit else ThreatKinematics()
        tactical.append(
            TacticalThreat(
                unit_id=assessment.unit_id,
                name=assessment.name,
                type_name=unit.type_name if unit else None,
                kind=kind,
                level=assessment.level,
                score=assessment.score,
                bearing_deg=assessment.bearing_deg,
                range_nm=round(range_nm, 1),
                altitude_ft=altitude_ft,
                braa=_braa(assessment, altitude_ft),
                reasons=assessment.reasons,
                kinematics=kinematics,
                tactical_priority=_priority(assessment.score, kind, kinematics),
            )
        )

    tactical.sort(key=lambda item: (item.tactical_priority, item.score), reverse=True)
    highest = tactical[0] if tactical else None
    overall = max((item.level for item in tactical), key=_level_rank, default=ThreatLevel.LOW)
    return TacticalSituationSummary(
        available=True,
        overall_level=overall,
        recommendation=_recommendation(overall),
        total_threats=len(tactical),
        air_threats=sum(item.kind is TacticalThreatKind.AIR for item in tactical),
        sam_threats=sum(item.kind is TacticalThreatKind.SAM for item in tactical),
        highest_priority=highest,
        priority_threats=tactical[: max(1, limit)],
    )


def _priority(score: float, kind: TacticalThreatKind, kinematics: ThreatKinematics) -> float:
    value = score
    if kind is TacticalThreatKind.AIR:
        if kinematics.aspect.value == "hot":
            value += 15
        elif kinematics.aspect.value == "flanking":
            value += 5
        if kinematics.range_trend.value == "closing":
            value += min(15, max(0, (kinematics.closure_kts or 0) / 40))
        elif kinematics.range_trend.value == "diverging":
            value -= 10
    return round(min(100, max(0, value)), 1)


def _level_rank(level: ThreatLevel) -> int:
    return {
        ThreatLevel.LOW: 0,
        ThreatLevel.MEDIUM: 1,
        ThreatLevel.HIGH: 2,
        ThreatLevel.CRITICAL: 3,
    }[level]


def _kind(category: UnitCategory, type_name: str | None) -> TacticalThreatKind:
    text = (type_name or "").casefold()
    sam_markers = ("sam", "sa-", "s-300", "s-400", "buk", "tor", "osa", "hawk", "patriot")
    if category is UnitCategory.GROUND and any(marker in text for marker in sam_markers):
        return TacticalThreatKind.SAM
    if category in {UnitCategory.AIRCRAFT, UnitCategory.HELICOPTER}:
        return TacticalThreatKind.AIR
    if category is UnitCategory.GROUND:
        return TacticalThreatKind.GROUND
    if category is UnitCategory.SHIP:
        return TacticalThreatKind.NAVAL
    return TacticalThreatKind.UNKNOWN


def _braa(assessment: ThreatAssessment, altitude_ft: int | None) -> str:
    altitude = f"{altitude_ft // 1000} thousand" if altitude_ft is not None else "altitude unknown"
    return f"BRAA {assessment.bearing_deg:03.0f} for {assessment.distance_m / 1852.0:.1f}, {altitude}"


def _recommendation(level: ThreatLevel) -> DefensiveRecommendation:
    return {
        ThreatLevel.LOW: DefensiveRecommendation.MONITOR,
        ThreatLevel.MEDIUM: DefensiveRecommendation.INCREASE_SEPARATION,
        ThreatLevel.HIGH: DefensiveRecommendation.DEFENSIVE,
        ThreatLevel.CRITICAL: DefensiveRecommendation.BREAK_CONTACT,
    }[level]
