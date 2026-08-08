from orion.tactical_kinematics import RangeTrend, ThreatAspect, ThreatKinematics
from orion.tactical_situation import TacticalThreat, TacticalThreatKind
from orion.threats import ThreatLevel


def _air_threat(name: str, score: float, priority: float, aspect: ThreatAspect, trend: RangeTrend):
    return TacticalThreat(
        unit_id=name.lower(),
        name=name,
        type_name="MiG-29",
        kind=TacticalThreatKind.AIR,
        level=ThreatLevel.HIGH,
        score=score,
        bearing_deg=45.0,
        range_nm=25.0,
        altitude_ft=18000,
        braa="BRAA 045 for 25.0, 18 thousand",
        kinematics=ThreatKinematics(
            aspect=aspect,
            range_trend=trend,
            closure_kts=450.0 if trend is RangeTrend.CLOSING else -250.0,
        ),
        tactical_priority=priority,
    )


def test_hot_closing_contact_can_outrank_cold_diverging_contact():
    hot = _air_threat("Hot", score=70.0, priority=92.0, aspect=ThreatAspect.HOT, trend=RangeTrend.CLOSING)
    cold = _air_threat("Cold", score=74.0, priority=64.0, aspect=ThreatAspect.COLD, trend=RangeTrend.DIVERGING)

    ordered = sorted([cold, hot], key=lambda item: (item.tactical_priority, item.score), reverse=True)

    assert ordered[0].name == "Hot"
    assert ordered[1].name == "Cold"


def test_equal_priority_falls_back_to_existing_threat_score():
    first = _air_threat("Higher score", score=80.0, priority=90.0, aspect=ThreatAspect.HOT, trend=RangeTrend.CLOSING)
    second = _air_threat("Lower score", score=75.0, priority=90.0, aspect=ThreatAspect.HOT, trend=RangeTrend.CLOSING)

    ordered = sorted([second, first], key=lambda item: (item.tactical_priority, item.score), reverse=True)

    assert ordered[0].name == "Higher score"
