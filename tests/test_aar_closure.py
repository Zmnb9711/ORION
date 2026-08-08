from __future__ import annotations

import pytest

import orion.aar_proactive as proactive_module
import orion.aar_rendezvous as rendezvous_module
from orion.aar_closure import ClosureBand, ClosureProfile, compute_closure, spoken_closure
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


def test_closure_profile_tightens_with_distance() -> None:
    far = _context(165, distance_km=7.0)
    far_assessment = compute_closure(far, far.tankers[0])
    assert far_assessment is not None
    assert far_assessment.profile == ClosureProfile.FAR
    assert far_assessment.band == ClosureBand.STABLE

    medium = _context(165, distance_km=3.0)
    medium_assessment = compute_closure(medium, medium.tankers[0])
    assert medium_assessment is not None
    assert medium_assessment.profile == ClosureProfile.MEDIUM
    assert medium_assessment.band == ClosureBand.HIGH

    close = _context(165, distance_km=1.5)
    close_assessment = compute_closure(close, close.tankers[0])
    assert close_assessment is not None
    assert close_assessment.profile == ClosureProfile.CLOSE
    assert close_assessment.band == ClosureBand.EXCESSIVE


def test_final_profile_is_most_conservative() -> None:
    context = _context(154, distance_km=0.7)
    assessment = compute_closure(context, context.tankers[0])
    assert assessment is not None
    assert assessment.profile == ClosureProfile.FINAL
    assert assessment.closure_mps == pytest.approx(4.0)
    assert assessment.band == ClosureBand.HIGH
    assert assessment.stable_limit_mps == pytest.approx(2.5722)


def test_missing_distance_uses_legacy_safe_profile() -> None:
    context = _context(160)
    context.tankers[0].distance_km = None
    assessment = compute_closure(context, context.tankers[0])
    assert assessment is not None
    assert assessment.profile == ClosureProfile.UNKNOWN
    assert assessment.stable_limit_mps == pytest.approx(15.0)
    assert assessment.high_limit_mps == pytest.approx(30.0)


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
    assert monitor.poll().should_announce is False

    excessive = _context(250)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: excessive)
    update = monitor.poll("ru")
    assert update.should_announce is True
    assert update.reason == "closure_excessive"
    assert update.closure is not None and update.closure.band == ClosureBand.EXCESSIVE
    assert "слишком высокое" in update.spoken_text
    assert "уз" in update.spoken_text


def test_distance_alone_can_tighten_band_and_trigger_callout(monkeypatch) -> None:
    initial = _context(160, distance_km=3.0)
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: initial)
    aar_rendezvous.execute("aar_start", "Start AAR")
    monitor = AarProactiveMonitor(aar_rendezvous)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: initial)
    assert monitor.poll().should_announce is False

    closer = _context(160, distance_km=1.5)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: closer)
    update = monitor.poll("ru")
    assert update.should_announce is True
    assert update.reason == "closure_high"
    assert update.closure is not None and update.closure.profile == ClosureProfile.CLOSE


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
