from __future__ import annotations

import pytest

import orion.aar_proactive as proactive_module
import orion.aar_rendezvous as rendezvous_module
from orion.aar_proactive import AarProactiveMonitor
from orion.aar_rendezvous import aar_rendezvous
from orion.aar_vertical import VerticalBand, compute_vertical, spoken_vertical
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset() -> None:
    aar_rendezvous.reset()
    yield
    aar_rendezvous.reset()


def _context(own_alt: float, *, distance_km: float = 2.0) -> LiveMissionContext:
    return LiveMissionContext(available=True, ownship=OwnshipContext(aircraft_type="FA-18C_hornet", latitude=41.0, longitude=41.0, altitude_m=own_alt, heading_deg=90, true_airspeed_mps=160), tankers=[SupportAsset(unit_id="tanker-1", callsign="Texaco", role=DcsRecipientType.TANKER, coalition=Coalition.BLUE, available=True, aar_available=True, latitude=41.0, longitude=41.02, altitude_m=7000, distance_km=distance_km, bearing_deg=90, heading_deg=90, speed_mps=150)])


def test_vertical_classifies_high_low_and_aligned() -> None:
    for altitude, expected in [(7300, VerticalBand.HIGH), (6700, VerticalBand.LOW), (7050, VerticalBand.ALIGNED)]:
        context = _context(altitude)
        assessment = compute_vertical(context, context.tankers[0])
        assert assessment is not None and assessment.band == expected


def test_vertical_tolerance_tightens_with_distance() -> None:
    far = _context(7200, distance_km=7.0)
    close = _context(7200, distance_km=1.0)
    assert compute_vertical(far, far.tankers[0]).band == VerticalBand.ALIGNED
    assert compute_vertical(close, close.tankers[0]).band == VerticalBand.HIGH


def test_blue_vertical_offset_is_spoken_in_feet() -> None:
    context = _context(7300)
    assessment = compute_vertical(context, context.tankers[0])
    text = spoken_vertical(assessment, context.tankers[0], "en")
    assert "feet" in text


def test_monitor_announces_vertical_band_change(monkeypatch) -> None:
    aligned = _context(7050)
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: aligned)
    aar_rendezvous.execute("aar_start", "Start AAR")
    monitor = AarProactiveMonitor(aar_rendezvous)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: aligned)
    assert monitor.poll().should_announce is False

    high = _context(7300)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: high)
    update = monitor.poll("ru")
    assert update.should_announce is True
    assert update.reason == "vertical_high"
    assert update.vertical is not None and update.vertical.band == VerticalBand.HIGH
    assert "Снижайтесь" in update.spoken_text
    assert "фут" in update.spoken_text
    assert monitor.poll("ru").should_announce is False
