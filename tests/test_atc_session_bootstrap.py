from fastapi.testclient import TestClient

from orion.app import app
from orion.atc_service import VirtualAtcService


def test_get_or_open_session_is_idempotent_for_same_context() -> None:
    service = VirtualAtcService()

    first, first_created = service.get_or_open_session(
        mission_id="mission-1",
        aircraft_id="hornet-1",
        facility_id="kutaisi",
        procedural_state="arrival_contact",
    )
    second, second_created = service.get_or_open_session(
        mission_id="mission-1",
        aircraft_id="hornet-1",
        facility_id="kutaisi",
        procedural_state="ground_taxi",
    )

    assert first_created is True
    assert second_created is False
    assert first.session_id == second.session_id
    assert second.procedural_state == "arrival_contact"


def test_close_session_releases_bootstrap_key_for_new_session() -> None:
    service = VirtualAtcService()
    first, _ = service.get_or_open_session(mission_id="m", aircraft_id="a", facility_id="f")

    service.close_session(first.session_id, reason="mission ended")
    second, created = service.get_or_open_session(mission_id="m", aircraft_id="a", facility_id="f")

    assert created is True
    assert second.session_id != first.session_id


def test_bootstrap_distinguishes_facilities() -> None:
    service = VirtualAtcService()
    one, _ = service.get_or_open_session(mission_id="m", aircraft_id="a", facility_id="kutaisi")
    two, _ = service.get_or_open_session(mission_id="m", aircraft_id="a", facility_id="batumi")

    assert one.session_id != two.session_id


def test_bootstrap_api_returns_same_session_on_retry() -> None:
    payload = {
        "mission_id": "bootstrap-api-mission",
        "aircraft_id": "bootstrap-api-hornet",
        "facility_id": "bootstrap-api-kutaisi",
        "procedural_state": "arrival_contact",
    }
    with TestClient(app) as client:
        first = client.post("/v1/atc/sessions/bootstrap", json=payload)
        second = client.post("/v1/atc/sessions/bootstrap", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["status"]["session_id"] == second.json()["status"]["session_id"]
