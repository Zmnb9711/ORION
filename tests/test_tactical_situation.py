from orion.mission import UnitCategory
from orion.tactical_situation import (
    DefensiveRecommendation,
    TacticalThreatKind,
    _kind,
    _recommendation,
    get_tactical_situation,
)
from orion.threats import ThreatLevel


def test_sam_detection_from_ground_unit_type():
    assert _kind(UnitCategory.GROUND, "SA-11 Buk SR 9S18M1") == TacticalThreatKind.SAM
    assert _kind(UnitCategory.GROUND, "S-300PS 40B6MD sr") == TacticalThreatKind.SAM


def test_air_and_nav_category_mapping():
    assert _kind(UnitCategory.AIRCRAFT, "MiG-29S") == TacticalThreatKind.AIR
    assert _kind(UnitCategory.HELICOPTER, "Ka-50") == TacticalThreatKind.AIR
    assert _kind(UnitCategory.SHIP, "MOSCOW") == TacticalThreatKind.NAVAL


def test_threat_level_maps_to_conservative_recommendation():
    assert _recommendation(ThreatLevel.LOW) == DefensiveRecommendation.MONITOR
    assert _recommendation(ThreatLevel.MEDIUM) == DefensiveRecommendation.INCREASE_SEPARATION
    assert _recommendation(ThreatLevel.HIGH) == DefensiveRecommendation.DEFENSIVE
    assert _recommendation(ThreatLevel.CRITICAL) == DefensiveRecommendation.BREAK_CONTACT


def test_tactical_summary_is_empty_without_live_mission_context():
    summary = get_tactical_situation()
    assert summary.available is False
    assert summary.total_threats == 0
    assert summary.highest_priority is None
