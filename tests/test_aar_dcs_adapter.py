from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import orion.aar_rendezvous as rendezvous_module
from orion.aar_dcs_adapter import AarRawObservation, AarRawSource, aar_dcs_adapter
from orion.aar_events import AarEventType, aar_events
from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.app import app
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset() -> None:
    aar_rendezvous.reset()
    aar_events.reset()
    aar_dcs_adapter.reset()
    yield
    aar_rendezvous.reset()
    aar_events.reset()
    aar_dcs_adapter.reset()


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


def test_adapter_turns_semantic_dcs_edges_into_normalized_events(monkeypatch) -> None:
    _start(monkeypatch)

    pre = aar_dcs_adapter.ingest(AarRawObservation(
        observation_id="obs-1",
        source=AarRawSource.EXPORT_LUA,
        tanker_unit_id="tanker-1",
        pre_contact_cleared=True,
        physical_contact=False,
        fuel_transfer_active=False,
    ))
    assert [event.event_type for event in pre.generated_events] == [AarEventType.PRE_CONTACT]
    assert aar_rendezvous.snapshot().phase == AarPhase.PRE_CONTACT

    contact = aar_dcs_adapter.ingest(AarRawObservation(
        observation_id="obs-2",
        source=AarRawSource.EXPORT_LUA,
        tanker_unit_id="tanker-1",
        physical_contact=True,
        fuel_transfer_active=True,
    ))
    assert [event.event_type for event in contact.generated_events] == [AarEventType.CONTACT, AarEventType.REFUELING]
    assert all(result.accepted for result in contact.event_results)
    assert aar_rendezvous.snapshot().phase == AarPhase.CONTACT
    assert aar_events.refueling_active is True

    disconnected = aar_dcs_adapter.ingest(AarRawObservation(
        observation_id="obs-3",
        source=AarRawSource.EXPORT_LUA,
        tanker_unit_id="tanker-1",
        physical_contact=False,
        fuel_transfer_active=False,
    ))
    assert [event.event_type for event in disconnected.generated_events] == [AarEventType.DISCONNECT]
    assert aar_rendezvous.snapshot().phase == AarPhase.PRE_CONTACT


def test_unchanged_snapshot_does_not_repeat_events(monkeypatch) -> None:
    _start(monkeypatch)
    first = AarRawObservation(observation_id="obs-1", source=AarRawSource.MISSION_PACK, tanker_unit_id="tanker-1", pre_contact_cleared=True)
    second = AarRawObservation(observation_id="obs-2", source=AarRawSource.MISSION_PACK, tanker_unit_id="tanker-1", pre_contact_cleared=True)
    assert len(aar_dcs_adapter.ingest(first).generated_events) == 1
    assert aar_dcs_adapter.ingest(second).generated_events == []
    assert len(aar_events.list()) == 1


def test_duplicate_observation_is_idempotent(monkeypatch) -> None:
    _start(monkeypatch)
    observation = AarRawObservation(observation_id="same-observation", source=AarRawSource.EXPORT_LUA, tanker_unit_id="tanker-1", pre_contact_cleared=True)
    first = aar_dcs_adapter.ingest(observation)
    second = aar_dcs_adapter.ingest(observation)
    assert len(first.generated_events) == 1
    assert second.generated_events == []
    assert len(aar_events.list()) == 1


def test_wrong_tanker_event_is_rejected_but_detector_does_not_replay_edge(monkeypatch) -> None:
    _start(monkeypatch)
    wrong = AarRawObservation(observation_id="wrong-1", source=AarRawSource.EXPORT_LUA, tanker_unit_id="other", pre_contact_cleared=True)
    result = aar_dcs_adapter.ingest(wrong)
    assert result.generated_events[0].event_type == AarEventType.PRE_CONTACT
    assert result.event_results[0].accepted is False

    unchanged = AarRawObservation(observation_id="wrong-2", source=AarRawSource.EXPORT_LUA, tanker_unit_id="other", pre_contact_cleared=True)
    assert aar_dcs_adapter.ingest(unchanged).generated_events == []
    assert aar_rendezvous.snapshot().phase == AarPhase.JOIN_UP


def test_complete_edge_finishes_confirmed_contact(monkeypatch) -> None:
    _start(monkeypatch)
    aar_dcs_adapter.ingest(AarRawObservation(observation_id="p", source=AarRawSource.TEST, tanker_unit_id="tanker-1", pre_contact_cleared=True))
    aar_dcs_adapter.ingest(AarRawObservation(observation_id="c", source=AarRawSource.TEST, tanker_unit_id="tanker-1", physical_contact=True))
    completed = aar_dcs_adapter.ingest(AarRawObservation(observation_id="done", source=AarRawSource.TEST, tanker_unit_id="tanker-1", refueling_complete=True))
    assert completed.generated_events[0].event_type == AarEventType.COMPLETE
    assert completed.event_results[0].accepted is True
    assert aar_rendezvous.snapshot().phase == AarPhase.COMPLETE


def test_raw_observation_api_uses_existing_aar_router(monkeypatch) -> None:
    _start(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/v1/aar/raw-observations",
        json={
            "observation_id": "api-raw-1",
            "source": "mission_pack",
            "tanker_unit_id": "tanker-1",
            "pre_contact_cleared": True,
        },
    )
    assert response.status_code == 202
    body = response.json()
    assert body["generated_events"][0]["event_type"] == "pre_contact"
    assert body["event_results"][0]["session"]["phase"] == "pre_contact"
