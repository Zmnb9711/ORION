from __future__ import annotations

from fastapi.testclient import TestClient

from orion.app import app


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
