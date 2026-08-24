from __future__ import annotations

from fastapi.testclient import TestClient

from orion.app import app
from orion.realtime_provider import RealtimeLiveStatus
from orion import realtime_tool_api


client = TestClient(app)


def test_realtime_tool_catalog_exposes_smoke_and_virtual_atc_tools() -> None:
    response = client.get("/v1/realtime/tools")
    assert response.status_code == 200
    payload = response.json()
    assert [tool["name"] for tool in payload["tools"]] == [
        "orion.test.ping",
        "orion.virtual_atc.request",
    ]


def test_realtime_ping_executes_locally() -> None:
    response = client.post(
        "/v1/realtime/tools/execute",
        json={"call_id": "call-1", "name": "orion.test.ping", "arguments": {"message": "qwen-smoke"}},
    )
    assert response.status_code == 200
    assert response.json() == {
        "call_id": "call-1",
        "name": "orion.test.ping",
        "ok": True,
        "output": {"status": "ok", "tool": "orion.test.ping", "message": "qwen-smoke"},
        "error": None,
    }


def test_realtime_tool_gate_rejects_non_smoke_tools() -> None:
    response = client.post(
        "/v1/realtime/tools/execute",
        json={"call_id": "call-2", "name": "orion.atc.clearance", "arguments": {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["output"] == {}
    assert "not enabled" in payload["error"]


def test_provider_neutral_status_does_not_start_a_session(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        realtime_tool_api.realtime_live,
        "status",
        lambda: RealtimeLiveStatus(),
    )
    response = client.get("/v1/realtime/live/status")
    assert response.status_code == 200
    assert response.json() == {
        "provider": None,
        "state": "stopped",
        "phase": "idle",
        "message": "Realtime voice is stopped",
        "session_id": None,
        "input_name": None,
        "output_name": None,
        "input_rate": None,
        "output_rate": None,
        "input_chunks": 0,
        "output_chunks": 0,
        "last_error": None,
    }


def test_provider_neutral_start_is_provider_discriminated(monkeypatch) -> None:  # noqa: ANN001
    seen: list[object] = []

    def start(request):  # noqa: ANN001, ANN202
        seen.append(request)
        return RealtimeLiveStatus(provider="yandex", state="starting", message="starting")

    monkeypatch.setattr(realtime_tool_api.realtime_live, "start", start)
    response = client.post(
        "/v1/realtime/live/start",
        json={"provider": "yandex", "api_key": "memory-only", "folder_id": "folder"},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "yandex"
    assert len(seen) == 1


def test_provider_neutral_start_reports_conflict(monkeypatch) -> None:  # noqa: ANN001
    def conflict(request):  # noqa: ANN001, ANN202
        raise ValueError("Stop current realtime provider first")

    monkeypatch.setattr(realtime_tool_api.realtime_live, "start", conflict)
    response = client.post(
        "/v1/realtime/live/start",
        json={"provider": "qwen", "api_key": "key", "workspace_id": "workspace"},
    )
    assert response.status_code == 409
    assert "Stop current" in response.json()["detail"]
