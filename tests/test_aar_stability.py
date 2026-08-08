from __future__ import annotations

import pytest

import orion.aar_proactive as proactive_module
import orion.aar_rendezvous as rendezvous_module
from orion.aar_closure import AarClosureAssessment, ClosureBand, ClosureProfile
from orion.aar_proactive import AarProactiveMonitor
from orion.aar_rendezvous import aar_rendezvous
from orion.aar_stability import evaluate_joinup_stability
from orion.aar_vertical import AarVerticalAssessment, VerticalBand
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset() -> None:
    aar_rendezvous.reset()
    yield
    aar_rendezvous.reset()


def _tanker(distance_km: float) -> SupportAsset:
    return SupportAsset(unit_id="tanker-1", callsign="Texaco", role=DcsRecipientType.TANKER, coalition=Coalition.BLUE, available=True, aar_available=True, latitude=41.0, longitude=41.005, altitude_m=7000, distance_km=distance_km, bearing_deg=90, heading_deg=90, speed_mps=150)


def _context(*, own_alt: float = 7000, own_speed: float = 155, distance_km: float = 0.7) -> LiveMissionContext:
    return LiveMissionContext(available=True, ownship=OwnshipContext(aircraft_type="FA-18C_hornet", latitude=41.0, longitude=41.0, altitude_m=own_alt, heading_deg=90, true_airspeed_mps=own_speed), tankers=[_tanker(distance_km)])


def _closure(closure_mps: float, band: ClosureBand) -> AarClosureAssessment:
    return AarClosureAssessment(
        closure_mps=closure_mps,
        band=band,
        profile=ClosureProfile.FINAL,
        stable_limit_mps=2.5722,
        high_limit_mps=5.1444,
    )


def test_stability_requires_range_closure_and_vertical() -> None:
    tanker = _tanker(0.7)
    ready = evaluate_joinup_stability(tanker, _closure(2, ClosureBand.HOLD), AarVerticalAssessment(offset_m=10, band=VerticalBand.ALIGNED))
    assert ready.ready_for_precontact is True
    assert ready.reasons == []

    not_ready = evaluate_joinup_stability(_tanker(1.2), _closure(20, ClosureBand.EXCESSIVE), AarVerticalAssessment(offset_m=200, band=VerticalBand.HIGH))
    assert not_ready.ready_for_precontact is False
    assert set(not_ready.reasons) == {"distance_not_final", "closure_not_stable", "vertical_not_aligned"}


def test_monitor_announces_precontact_readiness_once(monkeypatch) -> None:
    initial = _context(own_speed=165, distance_km=0.7)
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: initial)
    aar_rendezvous.execute("aar_start", "Start AAR")
    monitor = AarProactiveMonitor(aar_rendezvous)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: initial)
    monitor.poll()

    stable = _context(own_speed=151, distance_km=0.7)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: stable)
    update = monitor.poll("ru")
    assert update.should_announce is True
    assert update.reason == "precontact_ready"
    assert update.stability is not None and update.stability.ready_for_precontact is True
    assert "pre-contact" in update.spoken_text
    assert monitor.poll("ru").should_announce is False


def test_ready_recommendation_does_not_change_aar_phase(monkeypatch) -> None:
    context = _context(own_speed=151, distance_km=0.7)
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: context)
    aar_rendezvous.execute("aar_start", "Start AAR")
    monitor = AarProactiveMonitor(aar_rendezvous)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: context)
    monitor.poll()
    session = aar_rendezvous.snapshot()
    assert session.phase.value == "join_up"
