from __future__ import annotations

import pytest

import orion.aar_proactive as proactive_module
import orion.aar_rendezvous as rendezvous_module
from orion.aar_proactive import AarProactiveMonitor
from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset() -> None:
    aar_rendezvous.reset()
    yield
    aar_rendezvous.reset()


def _context(longitude: float = 41.2, distance_km: float = 18.52, tanker_heading_deg: float = 0.0) -> LiveMissionContext:
    return LiveMissionContext(
        available=True,
        ownship=OwnshipContext(aircraft_type="FA-18C_hornet", latitude=41.0, longitude=41.0, altitude_m=5000, heading_deg=90, true_airspeed_mps=250),
        tankers=[SupportAsset(unit_id="tanker-1", callsign="Texaco", role=DcsRecipientType.TANKER, coalition=Coalition.BLUE, available=True, aar_available=True, latitude=41.0, longitude=longitude, altitude_m=7000, distance_km=distance_km, bearing_deg=90, heading_deg=tanker_heading_deg, speed_mps=150, frequency_mhz=251.5, modulation="AM", tacan_channel=31, tacan_band="Y")],
    )


def _start(monkeypatch, context: LiveMissionContext) -> AarProactiveMonitor:
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: context)
    aar_rendezvous.execute("aar_start", "Start AAR")
    return AarProactiveMonitor(aar_rendezvous)


def test_first_poll_is_silent(monkeypatch) -> None:
    context = _context()
    monitor = _start(monkeypatch, context)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: context)
    update = monitor.poll()
    assert update.should_announce is False
    assert update.phase == AarPhase.RENDEZVOUS


def test_join_up_transition_announces_once(monkeypatch) -> None:
    far = _context()
    monitor = _start(monkeypatch, far)
    near = _context(longitude=41.02, distance_km=2.0)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: near)
    update = monitor.poll("ru")
    assert update.should_announce is True
    assert update.reason == "phase_transition"
    assert update.phase == AarPhase.JOIN_UP
    assert "join-up" in update.spoken_text
    again = monitor.poll("ru")
    assert again.should_announce is False


def test_small_guidance_changes_do_not_chatter(monkeypatch) -> None:
    first = _context()
    monitor = _start(monkeypatch, first)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: first)
    assert monitor.poll().should_announce is False
    small = _context(longitude=41.195, distance_km=18.0)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: small)
    assert monitor.poll().should_announce is False


def test_large_guidance_change_is_announced(monkeypatch) -> None:
    first = _context()
    monitor = _start(monkeypatch, first)
    contexts = [first, _context(longitude=41.2, distance_km=18.52, tanker_heading_deg=180.0)]
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: contexts.pop(0))
    assert monitor.poll().should_announce is False
    update = monitor.poll()
    assert update.should_announce is True
    assert update.reason in {"heading_change", "eta_change"}
    assert "Rendezvous update" in update.spoken_text
