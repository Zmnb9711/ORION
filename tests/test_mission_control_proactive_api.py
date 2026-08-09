from fastapi.testclient import TestClient

from orion.app import app
from orion.mission_control_proactive import proactive_mission_control


client = TestClient(app)


def test_proactive_status_endpoint_exposes_runtime_state() -> None:
    proactive_mission_control.disable()
    response = client.get("/v1/mission-control/proactive/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["active_action_id"] is None
    assert payload["deescalation_required"] >= 1
    assert payload["replacement_required"] >= 1
