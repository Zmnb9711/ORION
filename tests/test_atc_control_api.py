from fastapi.testclient import TestClient

from orion.app import app
from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_service import virtual_atc


def test_atc_integration_and_handoff_api() -> None:
    identity = AtcSessionIdentity(mission_id="api-test", aircraft_id="a1", facility_id="field")
    virtual_atc.open_session(identity, procedural_state="hold_short")
    virtual_atc.claim_authority(
        session_id=identity.session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.AIRPORT_TOWER,
        reason="tower control",
    )
    try:
        with TestClient(app) as client:
            mode = client.put(
                f"/v1/atc/sessions/{identity.session_id}/integration",
                json={"mode": "orion_with_native_fallback", "reason": "test degraded mode"},
            )
            assert mode.status_code == 200
            assert mode.json()["mode"] == "orion_with_native_fallback"

            started = client.post(
                "/v1/atc/handoffs/event-gated",
                json={
                    "session_id": str(identity.session_id),
                    "source": "airport_tower",
                    "destination": "airport_departure",
                    "scopes": ["flight_traffic"],
                    "reason": "transfer on departure event",
                },
            )
            assert started.status_code == 201
            handoff_id = started.json()["handoff_id"]

            owner = virtual_atc.core.authority.get_owner(
                identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC
            )
            assert owner is not None
            assert owner.agency is ControllerAgency.AIRPORT_TOWER

            completed = client.post(
                f"/v1/atc/handoffs/{handoff_id}/event",
                json={"event_name": "departure", "reason": "departure observed"},
            )
            assert completed.status_code == 200
            assert completed.json()["state"] == "completed"

            fetched = client.get(f"/v1/atc/handoffs/{handoff_id}")
            assert fetched.status_code == 200
            assert fetched.json()["destination_agency"] == "airport_departure"
    finally:
        if virtual_atc.sessions.get(identity.session_id) is not None:
            virtual_atc.close_session(identity.session_id, reason="test cleanup")
