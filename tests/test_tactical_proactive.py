from orion.tactical_kinematics import RangeTrend, ThreatAspect, ThreatKinematics
from orion.tactical_proactive import TacticalProactiveMonitor, _ThreatMemory, _callout, _meaningful_change
from orion.tactical_situation import TacticalThreat, TacticalThreatKind
from orion.threats import ThreatLevel


def _threat(level=ThreatLevel.HIGH, range_nm=25.0, kind=TacticalThreatKind.AIR):
    return TacticalThreat(
        unit_id="bandit-1",
        name="Bandit",
        type_name="MiG-29",
        kind=kind,
        level=level,
        score=75.0,
        bearing_deg=42.0,
        range_nm=range_nm,
        altitude_ft=18000,
        braa="BRAA 042 for 25.0, 18 thousand",
        kinematics=ThreatKinematics(
            aspect=ThreatAspect.HOT,
            range_trend=RangeTrend.CLOSING,
            closure_kts=480.0,
        ),
        tactical_priority=90.0,
    )


def test_high_threat_is_announced_once_then_suppressed():
    threat = _threat()
    assert _meaningful_change(threat, None) is True
    previous = _ThreatMemory(level=ThreatLevel.HIGH, range_nm=25.0)
    assert _meaningful_change(threat, previous) is False


def test_escalation_to_critical_is_announced():
    threat = _threat(level=ThreatLevel.CRITICAL)
    previous = _ThreatMemory(level=ThreatLevel.HIGH, range_nm=20.0)
    assert _meaningful_change(threat, previous) is True


def test_substantial_closure_is_reannounced_but_small_change_is_not():
    previous = _ThreatMemory(level=ThreatLevel.HIGH, range_nm=30.0)
    assert _meaningful_change(_threat(range_nm=19.5), previous) is True
    assert _meaningful_change(_threat(range_nm=24.0), previous) is False


def test_medium_threat_is_not_spoken_proactively():
    assert _meaningful_change(_threat(level=ThreatLevel.MEDIUM), None) is False


def test_monitor_can_reset_memory():
    monitor = TacticalProactiveMonitor()
    monitor._seen["x"] = _ThreatMemory(ThreatLevel.HIGH, 20.0)
    monitor.reset()
    assert monitor._seen == {}


def test_english_awacs_callout_includes_aspect_and_closure():
    text = _callout(_threat(), "en")
    assert "hot" in text
    assert "closing" in text
    assert "closure 480 knots" in text


def test_russian_awacs_callout_includes_kinematics():
    text = _callout(_threat(), "ru")
    assert "идёт навстречу" in text
    assert "сближается" in text
    assert "889 километров в час" in text
