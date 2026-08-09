from fastapi.testclient import TestClient

from orion.app import app
from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_service import virtual_atc


def test_atc_status_router_is_registered_in_main_app() -> None:
    identity = AtcSessionIdentity(mission_id="api-test", aircraft_id="viper", facility_id="airfield")
    virtual_atc.open_session(identity, procedural_state="taxi")
    virtual_atc.claim_authority(
        session_id=identity.session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.AIRPORT_GROUND,
        reason="API regression test",
    )

    with TestClient(app) as client:
        response = client.get(f"/v1/atc/sessions/{identity.session_id}/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == str(identity.session_id)
    assert payload["procedural_state"] == "taxi"
    assert payload["integration_mode"] == "orion_primary"
    assert payload["authority"]["flight_traffic"] == "airport_ground"

    virtual_atc.close_session(identity.session_id, reason="test cleanup")


def test_atc_close_endpoint_invalidates_live_status_but_keeps_audit_history() -> None:
    identity = AtcSessionIdentity(mission_id="api-test", aircraft_id="hornet", facility_id="cvn")
    virtual_atc.open_session(identity, procedural_state="inbound")

    with TestClient(app) as client:
        closed = client.delete(f"/v1/atc/sessions/{identity.session_id}")
        missing = client.get(f"/v1/atc/sessions/{identity.session_id}/status")

    assert closed.status_code == 204
    assert missing.status_code == 404
    event_types = [event.event_type for event in virtual_atc.core.history.list(identity.session_id)]
    assert "session_closed" in event_types


def test_atc_status_returns_404_for_unknown_session() -> None:
    identity = AtcSessionIdentity(mission_id="api-test", aircraft_id="missing")

    with TestClient(app) as client:
        response = client.get(f"/v1/atc/sessions/{identity.session_id}/status")

    assert response.status_code == 404
