from __future__ import annotations

import pytest

import orion.aar_proactive as proactive_module
import orion.aar_rendezvous as rendezvous_module
from orion.aar_closure import ClosureBand, compute_closure, spoken_closure
from orion.aar_proactive import AarProactiveMonitor
from orion.aar_rendezvous import aar_rendezvous
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset() -> None:
    aar_rendezvous.reset()
    yield
    aar_rendezvous.reset()


def _context(own_speed: float, *, distance_km: float = 2.0) -> LiveMissionContext:
    return LiveMissionContext(
        available=True,
        ownship=OwnshipContext(
            aircraft_type="FA-18C_hornet",
            latitude=41.0,
            longitude=41.0,
            altitude_m=5000,
            heading_deg=90,
            true_airspeed_mps=own_speed,
        ),
        tankers=[SupportAsset(
            unit_id="tanker-1",
            callsign="Texaco",
            role=DcsRecipientType.TANKER,
            coalition=Coalition.BLUE,
            available=True,
            aar_available=True,
            latitude=41.0,
            longitude=41.02,
            altitude_m=7000,
            distance_km=distance_km,
            bearing_deg=90,
            heading_deg=90,
            speed_mps=150,
        )],
    )


def test_closure_projects_relative_velocity_on_line_of_sight() -> None:
    context = _context(250)
    assessment = compute_closure(context, context.tankers[0])
    assert assessment is not None
    assert assessment.closure_mps == pytest.approx(100.0)
    assert assessment.band == ClosureBand.EXCESSIVE


def test_closure_classifies_stable_and_opening() -> None:
    stable = _context(160)
    stable_assessment = compute_closure(stable, stable.tankers[0])
    assert stable_assessment is not None and stable_assessment.band == ClosureBand.STABLE

    opening = _context(140)
    opening_assessment = compute_closure(opening, opening.tankers[0])
    assert opening_assessment is not None and opening_assessment.band == ClosureBand.OPENING


def test_blue_closure_is_spoken_in_knots() -> None:
    context = _context(160)
    assessment = compute_closure(context, context.tankers[0])
    assert assessment is not None
    text = spoken_closure(assessment, context.tankers[0], "en")
    assert "knots" in text
    assert "19" in text


def test_join_up_monitor_announces_closure_band_change(monkeypatch) -> None:
    stable = _context(160)
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: stable)
    aar_rendezvous.execute("aar_start", "Start AAR")
    monitor = AarProactiveMonitor(aar_rendezvous)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: stable)
    # Establish the initial stable closure band without a callout.
    assert monitor.poll().should_announce is False

    excessive = _context(250)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: excessive)
    update = monitor.poll("ru")
    assert update.should_announce is True
    assert update.reason == "closure_excessive"
    assert update.closure is not None and update.closure.band == ClosureBand.EXCESSIVE
    assert "слишком высокое" in update.spoken_text
    assert "уз" in update.spoken_text


def test_same_closure_band_does_not_repeat_callout(monkeypatch) -> None:
    stable = _context(160)
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: stable)
    aar_rendezvous.execute("aar_start", "Start AAR")
    monitor = AarProactiveMonitor(aar_rendezvous)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: stable)
    monitor.poll()

    high = _context(170)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: high)
    first = monitor.poll()
    assert first.should_announce is True
    assert first.reason == "closure_high"
    second = monitor.poll()
    assert second.should_announce is False
