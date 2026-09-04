from __future__ import annotations

from fastapi.testclient import TestClient

from orion.app import app
from orion.live_golden_conversation import InformationalPresentationBackend
from orion.live_golden_conversation_api import LiveGoldenStart


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


def test_live_golden_backend_selector_is_explicit_and_qwen_safe_by_default() -> None:
    default = LiveGoldenStart()
    candidate = LiveGoldenStart(
        informational_backend="REALTIME_D75_CANDIDATE"
    )

    assert default.informational_backend is (
        InformationalPresentationBackend.CURRENT_QWEN
    )
    assert candidate.informational_backend is (
        InformationalPresentationBackend.REALTIME_D75_CANDIDATE
    )
