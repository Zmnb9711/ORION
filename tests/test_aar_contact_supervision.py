from __future__ import annotations

import pytest

import orion.aar_contact_monitor as monitor_module
import orion.aar_rendezvous as rendezvous_module
from orion.aar_contact_monitor import AarContactMonitor
from orion.aar_contact_supervision import evaluate_contact_supervision
from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.aar_closure import compute_closure
from orion.aar_vertical import compute_vertical
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset() -> None:
    aar_rendezvous.reset()
    yield
    aar_rendezvous.reset()


def _context(*, distance_km: float = 0.1, own_speed: float = 150.0, own_alt: float = 7000.0) -> LiveMissionContext:
    return LiveMissionContext(
        available=True,
        ownship=OwnshipContext(
            aircraft_type="FA-18C_hornet",
            latitude=41.0,
            longitude=41.0,
            altitude_m=own_alt,
            heading_deg=90.0,
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
            longitude=41.001,
            altitude_m=7000.0,
            distance_km=distance_km,
            bearing_deg=90.0,
            heading_deg=90.0,
            speed_mps=150.0,
        )],
    )


def _enter_contact(monkeypatch, context: LiveMissionContext) -> AarContactMonitor:
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: context)
    aar_rendezvous.execute("aar_start", "Start AAR")
    pre = aar_rendezvous.execute("aar_pre_contact", "Pre-contact")
    assert pre.completed is True and pre.session.phase == AarPhase.PRE_CONTACT
    contact = aar_rendezvous.execute("aar_contact", "Contact with tanker")
    assert contact.session.phase == AarPhase.CONTACT
    monkeypatch.setattr(monitor_module, "build_live_mission_context", lambda: context)
    return AarContactMonitor(aar_rendezvous)


def test_contact_supervision_requires_tight_range_closure_and_vertical() -> None:
    context = _context()
    tanker = context.tankers[0]
    supervision = evaluate_contact_supervision(tanker, compute_closure(context, tanker), compute_vertical(context, tanker))
    assert supervision.stable is True
    assert supervision.reasons == []


def test_contact_monitor_announces_degradation_and_restoration(monkeypatch) -> None:
    stable = _context()
    monitor = _enter_contact(monkeypatch, stable)
    assert monitor.poll("ru").should_announce is False

    degraded = _context(distance_km=0.3, own_speed=158.0, own_alt=7030.0)
    monkeypatch.setattr(monitor_module, "build_live_mission_context", lambda: degraded)
    update = monitor.poll("ru")
    assert update.should_announce is True
    assert update.reason == "contact_degraded"
    assert "disconnect" in update.spoken_text
    assert set(update.supervision.reasons) == {
        "contact_range_degraded",
        "contact_closure_degraded",
        "contact_vertical_degraded",
    }
    assert monitor.poll("ru").should_announce is False

    monkeypatch.setattr(monitor_module, "build_live_mission_context", lambda: stable)
    restored = monitor.poll("ru")
    assert restored.should_announce is True
    assert restored.reason == "contact_stable_restored"
    assert "Держать" in restored.spoken_text


def test_monitor_never_changes_contact_phase(monkeypatch) -> None:
    stable = _context()
    monitor = _enter_contact(monkeypatch, stable)
    degraded = _context(distance_km=0.4, own_speed=160.0, own_alt=7050.0)
    monkeypatch.setattr(monitor_module, "build_live_mission_context", lambda: degraded)
    monitor.poll()
    assert aar_rendezvous.snapshot().phase == AarPhase.CONTACT
