from orion.mission import MissionPosition, MissionUnit, UnitCategory, Coalition
from orion.tactical_kinematics import ThreatAspect, RangeTrend, assess_threat_kinematics
from orion.tactical_situation import TacticalThreatKind, _priority


def _aircraft(heading: float, speed_mps: float = 250.0) -> MissionUnit:
    return MissionUnit(
        unit_id="bandit-1",
        name="Bandit",
        coalition=Coalition.RED,
        category=UnitCategory.AIRCRAFT,
        type_name="MiG-29",
        position=MissionPosition(latitude=0.0, longitude=0.1, altitude_m=5000),
        heading_deg=heading,
        speed_mps=speed_mps,
    )


def test_hot_contact_is_closing():
    ownship = MissionPosition(latitude=0.0, longitude=0.0, altitude_m=5000)
    result = assess_threat_kinematics(_aircraft(270.0), ownship)
    assert result.aspect is ThreatAspect.HOT
    assert result.range_trend is RangeTrend.CLOSING
    assert result.closure_kts is not None and result.closure_kts > 400


def test_cold_contact_is_diverging():
    ownship = MissionPosition(latitude=0.0, longitude=0.0, altitude_m=5000)
    result = assess_threat_kinematics(_aircraft(90.0), ownship)
    assert result.aspect is ThreatAspect.COLD
    assert result.range_trend is RangeTrend.DIVERGING
    assert result.closure_kts is not None and result.closure_kts < -400


def test_flanking_contact_has_small_radial_closure():
    ownship = MissionPosition(latitude=0.0, longitude=0.0, altitude_m=5000)
    result = assess_threat_kinematics(_aircraft(0.0), ownship)
    assert result.aspect is ThreatAspect.FLANKING
    assert result.range_trend is RangeTrend.STABLE
    assert abs(result.closure_kts or 0.0) < 25


def test_hot_closing_air_threat_gets_more_priority_than_cold():
    ownship = MissionPosition(latitude=0.0, longitude=0.0, altitude_m=5000)
    hot = assess_threat_kinematics(_aircraft(270.0), ownship)
    cold = assess_threat_kinematics(_aircraft(90.0), ownship)
    assert _priority(60.0, TacticalThreatKind.AIR, hot) > _priority(60.0, TacticalThreatKind.AIR, cold)
