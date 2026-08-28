from __future__ import annotations

from fastapi.testclient import TestClient

from orion.app import app


def test_core_exposes_bounded_live_golden_lifecycle_endpoints() -> None:
    client = TestClient(app)
    status = client.get("/v1/realtime/live-golden-conversation/status")
    assert status.status_code == 200
    assert status.json()["state"] == "off"
    blocked = client.post(
        "/v1/realtime/live-golden-conversation/start",
        json={"capture_response_audio": True},
    )
    assert blocked.status_code == 409
    assert "Yandex + SRS" in blocked.json()["detail"]
    stopped = client.post("/v1/realtime/live-golden-conversation/stop")
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "off"
