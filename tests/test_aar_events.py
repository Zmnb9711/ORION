from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import orion.aar_rendezvous as rendezvous_module
from orion.aar_events import AarEvent, AarEventSource, AarEventType, aar_events
from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.app import app
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset() -> None:
    aar_rendezvous.reset()
    aar_events.reset()
    yield
    aar_rendezvous.reset()
    aar_events.reset()


def _context() -> LiveMissionContext:
    return LiveMissionContext(
        available=True,
        ownship=OwnshipContext(
            aircraft_type="FA-18C_hornet",
            latitude=41.0,
            longitude=41.0,
            altitude_m=7000,
            heading_deg=90,
            true_airspeed_mps=151,
        ),
        tankers=[
            SupportAsset(
                unit_id="tanker-1",
                callsign="Texaco",
                role=DcsRecipientType.TANKER,
                coalition=Coalition.BLUE,
                available=True,
                aar_available=True,
                latitude=41.0,
                longitude=41.004,
                altitude_m=7000,
                distance_km=0.4,
                bearing_deg=90,
                heading_deg=90,
                speed_mps=150,
            )
        ],
    )


def _start(monkeypatch) -> None:
    monkeypatch.setattr(rendezvous_module, "build_live_mission_context", _context)
    result = aar_rendezvous.execute("aar_start", "Start AAR")
    assert result.session.phase == AarPhase.JOIN_UP


def _event(event_id: str, event_type: AarEventType, tanker: str = "tanker-1") -> AarEvent:
    return AarEvent(event_id=event_id, event_type=event_type, source=AarEventSource.DCS, tanker_unit_id=tanker)


def test_confirmed_dcs_events_drive_narrow_state_machine(monkeypatch) -> None:
    _start(monkeypatch)
    pre = aar_events.ingest(_event("e1", AarEventType.PRE_CONTACT))
    assert pre.accepted is True and pre.session.phase == AarPhase.PRE_CONTACT

    contact = aar_events.ingest(_event("e2", AarEventType.CONTACT))
    assert contact.accepted is True and contact.session.phase == AarPhase.CONTACT

    refueling = aar_events.ingest(_event("e3", AarEventType.REFUELING))
    assert refueling.accepted is True
    assert aar_events.refueling_active is True
    assert refueling.session.phase == AarPhase.CONTACT

    disconnect = aar_events.ingest(_event("e4", AarEventType.DISCONNECT))
    assert disconnect.accepted is True and disconnect.session.phase == AarPhase.PRE_CONTACT
    assert aar_events.refueling_active is False


def test_complete_requires_confirmed_contact(monkeypatch) -> None:
    _start(monkeypatch)
    rejected = aar_events.ingest(_event("e1", AarEventType.COMPLETE))
    assert rejected.accepted is False
    assert aar_rendezvous.snapshot().phase == AarPhase.JOIN_UP


def test_complete_from_contact_finishes_session(monkeypatch) -> None:
    _start(monkeypatch)
    aar_events.ingest(_event("e1", AarEventType.PRE_CONTACT))
    aar_events.ingest(_event("e2", AarEventType.CONTACT))
    completed = aar_events.ingest(_event("e3", AarEventType.COMPLETE))
    assert completed.accepted is True and completed.session.phase == AarPhase.COMPLETE


def test_duplicate_event_is_idempotent(monkeypatch) -> None:
    _start(monkeypatch)
    event = _event("same", AarEventType.PRE_CONTACT)
    first = aar_events.ingest(event)
    second = aar_events.ingest(event)
    assert first.accepted is True
    assert second.accepted is True and second.duplicate is True
    assert len(aar_events.list()) == 1


def test_wrong_tanker_is_rejected(monkeypatch) -> None:
    _start(monkeypatch)
    result = aar_events.ingest(_event("e1", AarEventType.PRE_CONTACT, tanker="other-tanker"))
    assert result.accepted is False
    assert aar_rendezvous.snapshot().phase == AarPhase.JOIN_UP


def test_refueling_requires_contact(monkeypatch) -> None:
    _start(monkeypatch)
    result = aar_events.ingest(_event("e1", AarEventType.REFUELING))
    assert result.accepted is False
    assert aar_events.refueling_active is False


def test_api_ingests_and_lists_events(monkeypatch) -> None:
    _start(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/v1/aar/events",
        json={"event_id": "api-1", "event_type": "pre_contact", "source": "mission_pack", "tanker_unit_id": "tanker-1"},
    )
    assert response.status_code == 202
    assert response.json()["session"]["phase"] == "pre_contact"
    listed = client.get("/v1/aar/events")
    assert listed.status_code == 200
    assert listed.json()[0]["event_id"] == "api-1"
