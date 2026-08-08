from orion.threat_trend_history import SustainedThreatTrend, ThreatTrendTracker


def test_requires_multiple_samples_before_declaring_trend():
    tracker = ThreatTrendTracker()
    assert tracker.observe("bandit", 30).trend is SustainedThreatTrend.INSUFFICIENT_DATA
    assert tracker.observe("bandit", 28).trend is SustainedThreatTrend.INSUFFICIENT_DATA


def test_sustained_closing_range_is_detected():
    tracker = ThreatTrendTracker()
    tracker.observe("bandit", 30)
    tracker.observe("bandit", 27)
    result = tracker.observe("bandit", 24)
    assert result.trend is SustainedThreatTrend.CLOSING
    assert result.sustained is True
    assert result.range_change_nm == -6


def test_sustained_diverging_range_is_detected():
    tracker = ThreatTrendTracker()
    tracker.observe("bandit", 20)
    tracker.observe("bandit", 23)
    result = tracker.observe("bandit", 26)
    assert result.trend is SustainedThreatTrend.DIVERGING
    assert result.sustained is True
    assert result.range_change_nm == 6


def test_small_range_jitter_is_treated_as_stable():
    tracker = ThreatTrendTracker(noise_nm=0.5)
    tracker.observe("bandit", 20.0)
    tracker.observe("bandit", 20.2)
    result = tracker.observe("bandit", 19.9)
    assert result.trend is SustainedThreatTrend.STABLE
    assert result.sustained is True


def test_mixed_direction_is_not_a_sustained_trend():
    tracker = ThreatTrendTracker()
    tracker.observe("bandit", 30)
    tracker.observe("bandit", 26)
    result = tracker.observe("bandit", 29)
    assert result.trend is SustainedThreatTrend.STABLE
    assert result.sustained is False


def test_retain_discards_contacts_no_longer_present():
    tracker = ThreatTrendTracker()
    tracker.observe("keep", 10)
    tracker.observe("drop", 20)
    tracker.retain({"keep"})
    assert tracker.observe("drop", 19).samples == 1
