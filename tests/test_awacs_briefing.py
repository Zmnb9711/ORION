from orion.awacs_briefing import build_awacs_briefing
from orion.tactical_kinematics import RangeTrend, ThreatAspect, ThreatKinematics
from orion.tactical_situation import TacticalThreat, TacticalThreatKind
from orion.threats import ThreatLevel


def _air(
    unit_id: str,
    priority: float,
    score: float = 70.0,
    range_nm: float = 30.0,
    aspect: ThreatAspect = ThreatAspect.HOT,
    trend: RangeTrend = RangeTrend.CLOSING,
    level: ThreatLevel = ThreatLevel.HIGH,
) -> TacticalThreat:
    return TacticalThreat(
        unit_id=unit_id,
        name=unit_id,
        type_name="MiG-29",
        kind=TacticalThreatKind.AIR,
        level=level,
        score=score,
        bearing_deg=45.0,
        range_nm=range_nm,
        altitude_ft=20000,
        braa=f"BRAA 045 for {range_nm:.1f}, 20 thousand",
        kinematics=ThreatKinematics(
            aspect=aspect,
            range_trend=trend,
            closure_kts=400.0 if trend is RangeTrend.CLOSING else -250.0,
        ),
        tactical_priority=priority,
    )


def test_briefing_has_one_primary_and_at_most_two_secondary_contacts():
    plan = build_awacs_briefing([
        _air("a", 95),
        _air("b", 90),
        _air("c", 85),
        _air("d", 80),
    ])
    assert plan.primary is not None
    assert plan.primary.unit_id == "a"
    assert [item.unit_id for item in plan.secondary] == ["b", "c"]


def test_briefing_preserves_awacs_priority_order():
    plan = build_awacs_briefing([
        _air("cold-near", 80, score=80, range_nm=10, aspect=ThreatAspect.COLD, trend=RangeTrend.DIVERGING),
        _air("hot-closing", 92, score=72, range_nm=25),
    ])
    assert plan.primary is not None
    assert plan.primary.unit_id == "hot-closing"
    assert plan.secondary[0].unit_id == "cold-near"


def test_low_value_cold_diverging_contact_is_suppressed():
    plan = build_awacs_briefing([
        _air("primary", 95),
        _air("cold-far", 55, range_nm=45, aspect=ThreatAspect.COLD, trend=RangeTrend.DIVERGING),
    ])
    assert plan.primary is not None
    assert plan.primary.unit_id == "primary"
    assert plan.secondary == []


def test_critical_secondary_is_kept_even_when_priority_gap_is_large():
    plan = build_awacs_briefing([
        _air("primary", 98),
        _air("critical", 50, aspect=ThreatAspect.COLD, trend=RangeTrend.DIVERGING, level=ThreatLevel.CRITICAL),
    ])
    assert [item.unit_id for item in plan.secondary] == ["critical"]


def test_briefing_empty_without_air_contacts():
    ground = _air("sam", 99).model_copy(update={"kind": TacticalThreatKind.SAM})
    plan = build_awacs_briefing([ground])
    assert plan.primary is None
    assert plan.secondary == []
