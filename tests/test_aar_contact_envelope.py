from __future__ import annotations

import pytest

import orion.aar_proactive as proactive_module
import orion.aar_rendezvous as rendezvous_module
from orion.aar_closure import AarClosureAssessment, ClosureBand, ClosureProfile
from orion.aar_contact_envelope import evaluate_contact_envelope
from orion.aar_proactive import AarProactiveMonitor
from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.aar_vertical import AarVerticalAssessment, VerticalBand
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset() -> None:
    aar_rendezvous.reset()
    yield
    aar_rendezvous.reset()


def _context(*, distance_km: float = 0.4, own_speed: float = 151.0, own_alt: float = 7000.0) -> LiveMissionContext:
    return LiveMissionContext(
        available=True,
        ownship=OwnshipContext(aircraft_type="FA-18C_hornet", latitude=41.0, longitude=41.0, altitude_m=own_alt, heading_deg=90, true_airspeed_mps=own_speed),
        tankers=[SupportAsset(unit_id="tanker-1", callsign="Texaco", role=DcsRecipientType.TANKER, coalition=Coalition.BLUE, available=True, aar_available=True, latitude=41.0, longitude=41.004, altitude_m=7000, distance_km=distance_km, bearing_deg=90, heading_deg=90, speed_mps=150)],
    )


def _closure(value: float) -> AarClosureAssessment:
    return AarClosureAssessment(closure_mps=value, band=ClosureBand.HOLD, profile=ClosureProfile.FINAL, stable_limit_mps=2.5722, high_limit_mps=5.1444)


def test_contact_envelope_requires_tight_range_closure_and_vertical() -> None:
    tanker = _context().tankers[0]
    good = evaluate_contact_envelope(tanker, _closure(1.0), AarVerticalAssessment(offset_m=5, band=VerticalBand.ALIGNED))
    assert good.within_envelope is True
    bad = evaluate_contact_envelope(_context(distance_km=0.7).tankers[0], _closure(4.0), AarVerticalAssessment(offset_m=30, band=VerticalBand.ALIGNED))
    assert bad.within_envelope is False
    assert set(bad.reasons) == {"distance_outside_contact_envelope", "closure_outside_contact_envelope", "vertical_outside_contact_envelope"}


def test_precontact_monitor_announces_envelope_loss_and_restore(monkeypatch) -> None:
    stable = _context()
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: stable)
    aar_rendezvous.execute("aar_start", "Start AAR")
    pre = aar_rendezvous.execute("aar_pre_contact", "Pre-contact")
    assert pre.completed is True and pre.session.phase == AarPhase.PRE_CONTACT

    monitor = AarProactiveMonitor(aar_rendezvous)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: stable)
    first = monitor.poll("ru")
    assert first.should_announce is False
    assert first.contact_envelope is not None and first.contact_envelope.within_envelope is True

    unstable = _context(distance_km=0.7, own_speed=160, own_alt=7040)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: unstable)
    lost = monitor.poll("ru")
    assert lost.should_announce is True
    assert lost.reason == "contact_envelope_lost"
    assert "Вне contact envelope" in lost.spoken_text
    assert monitor.poll("ru").should_announce is False

    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: stable)
    restored = monitor.poll("ru")
    assert restored.should_announce is True
    assert restored.reason == "contact_envelope_restored"


def test_precontact_monitor_never_declares_actual_contact(monkeypatch) -> None:
    stable = _context()
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: stable)
    aar_rendezvous.execute("aar_start", "Start AAR")
    aar_rendezvous.execute("aar_pre_contact", "Pre-contact")
    monitor = AarProactiveMonitor(aar_rendezvous)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: stable)
    for _ in range(3):
        monitor.poll()
    assert aar_rendezvous.snapshot().phase == AarPhase.PRE_CONTACT
