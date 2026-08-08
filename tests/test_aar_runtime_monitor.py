from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import orion.aar_proactive as proactive_module
import orion.aar_rendezvous as rendezvous_module
import orion.aar_runtime_monitor as runtime_monitor_module
from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.aar_runtime_monitor import aar_runtime_monitor
from orion.app import app
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset() -> None:
    aar_rendezvous.reset()
    aar_runtime_monitor.reset()
    yield
    aar_rendezvous.reset()
    aar_runtime_monitor.reset()


def _context(with_tanker: bool = True, distance_km: float = 18.52) -> LiveMissionContext:
    tankers = []
    if with_tanker:
        tankers = [
            SupportAsset(
                unit_id="tanker-1",
                callsign="Texaco",
                role=DcsRecipientType.TANKER,
                coalition=Coalition.BLUE,
                available=True,
                aar_available=True,
                latitude=41.0,
                longitude=41.2,
                altitude_m=7000,
                distance_km=distance_km,
                bearing_deg=90,
                heading_deg=0,
                speed_mps=150,
                frequency_mhz=251.5,
                modulation="AM",
                tacan_channel=31,
                tacan_band="Y",
            )
        ]
    return LiveMissionContext(
        available=True,
        ownship=OwnshipContext(
            aircraft_type="FA-18C_hornet",
            latitude=41.0,
            longitude=41.0,
            altitude_m=5000,
            heading_deg=90,
            true_airspeed_mps=250,
        ),
        tankers=tankers,
    )


def _start(monkeypatch) -> None:
    context = _context()
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", lambda: context)
    result = aar_rendezvous.execute("aar_start", "Start AAR")
    assert result.session.phase is AarPhase.RENDEZVOUS


def test_lost_tanker_announces_once_and_restoration_announces(monkeypatch) -> None:
    _start(monkeypatch)
    missing = _context(with_tanker=False)
    monkeypatch.setattr(runtime_monitor_module, "build_live_mission_context", lambda: missing)

    first = aar_runtime_monitor.poll("en")
    assert first.active_tanker_present is False
    assert first.update.should_announce is True
    assert first.update.reason == "active_tanker_lost"

    second = aar_runtime_monitor.poll("en")
    assert second.update.should_announce is False

    restored = _context()
    monkeypatch.setattr(runtime_monitor_module, "build_live_mission_context", lambda: restored)
    third = aar_runtime_monitor.poll("en")
    assert third.active_tanker_present is True
    assert third.update.should_announce is True
    assert third.update.reason == "active_tanker_restored"
    assert "Texaco" in third.update.spoken_text


def test_present_tanker_delegates_to_existing_sparse_monitor(monkeypatch) -> None:
    _start(monkeypatch)
    context = _context()
    monkeypatch.setattr(runtime_monitor_module, "build_live_mission_context", lambda: context)
    monkeypatch.setattr(proactive_module, "build_live_mission_context", lambda: context)

    result = aar_runtime_monitor.poll("en")
    assert result.active_tanker_present is True
    assert result.update.should_announce is False
    assert result.update.phase is AarPhase.RENDEZVOUS


def test_proactive_api_exposes_runtime_monitor(monkeypatch) -> None:
    _start(monkeypatch)
    missing = _context(with_tanker=False)
    monkeypatch.setattr(runtime_monitor_module, "build_live_mission_context", lambda: missing)

    with TestClient(app) as client:
        response = client.get("/v1/aar/proactive", params={"language": "ru"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_tanker_present"] is False
    assert payload["update"]["should_announce"] is True
    assert payload["update"]["reason"] == "active_tanker_lost"
    assert "танкер" in payload["update"]["spoken_text"].lower()
