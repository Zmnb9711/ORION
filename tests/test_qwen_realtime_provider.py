from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from orion import qwen_realtime_provider
from orion.qwen_realtime_provider import QwenRealtimeConfig, QwenRealtimeProvider, build_qwen_realtime_url


class _FakeWebSocket:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self.events = list(events)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self) -> str:
        if not self.events:
            raise RuntimeError("no fake event")
        return json.dumps(self.events.pop(0))

    def close(self) -> None:
        self.closed = True


def _config() -> QwenRealtimeConfig:
    return QwenRealtimeConfig(api_key="test-key", workspace_id="ws-123", core_base_url="http://127.0.0.1:8000")


def test_build_qwen_url_is_workspace_scoped() -> None:
    assert build_qwen_realtime_url(_config()) == (
        "wss://ws-123.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen3.5-omni-flash-realtime"
    )


def test_build_qwen_url_rejects_unknown_region() -> None:
    config = QwenRealtimeConfig(api_key="x", workspace_id="ws", region="moon")
    with pytest.raises(ValueError, match="Unsupported Qwen region"):
        build_qwen_realtime_url(config)


def test_build_qwen_url_requires_workspace_and_model() -> None:
    with pytest.raises(ValueError, match="Workspace ID"):
        build_qwen_realtime_url(QwenRealtimeConfig(api_key="x", workspace_id=""))
    with pytest.raises(ValueError, match="model"):
        build_qwen_realtime_url(QwenRealtimeConfig(api_key="x", workspace_id="ws", model=""))


def test_connect_explicitly_enables_websocket_multithread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def create_connection(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setitem(
        sys.modules,
        "websocket",
        SimpleNamespace(create_connection=create_connection),
    )

    QwenRealtimeProvider(_config())._connect()

    assert captured["enable_multithread"] is True
    assert captured["timeout"] == _config().timeout_s


def test_connection_smoke_waits_for_session_updated(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _FakeWebSocket([{"type": "session.created"}, {"type": "session.updated"}])
    provider = QwenRealtimeProvider(_config())
    monkeypatch.setattr(provider, "_connect", lambda: ws)

    result = provider.test_connection()

    assert result.ok is True
    assert result.provider == "qwen_realtime"
    assert ws.sent[0]["type"] == "session.update"
    assert ws.closed is True


def test_connection_smoke_surfaces_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _FakeWebSocket([{"type": "error", "error": {"code": "bad_auth", "message": "invalid key"}}])
    provider = QwenRealtimeProvider(_config())
    monkeypatch.setattr(provider, "_connect", lambda: ws)

    result = provider.test_connection()

    assert result.ok is False
    assert result.state.value == "error"
    assert "invalid key" in result.message
    assert ws.closed is True


def test_tool_smoke_maps_qwen_function_to_local_orion_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _FakeWebSocket(
        [
            {"type": "session.created"},
            {"type": "session.updated"},
            {
                "type": "response.function_call_arguments.done",
                "call_id": "call-42",
                "name": "orion_test_ping",
                "arguments": '{"message":"qwen-smoke"}',
            },
            {"type": "response.text.delta", "delta": "Smoke "},
            {"type": "response.text.done", "text": "Smoke passed"},
            {"type": "response.done"},
        ]
    )
    provider = QwenRealtimeProvider(_config())
    monkeypatch.setattr(provider, "_connect", lambda: ws)
    calls: list[tuple[str, str, str]] = []

    def fake_core(config: QwenRealtimeConfig, call_id: str, provider_name: str, arguments: str):  # noqa: ANN202
        calls.append((call_id, provider_name, arguments))
        return {
            "call_id": call_id,
            "name": "orion.test.ping",
            "ok": True,
            "output": {"status": "ok", "tool": "orion.test.ping", "message": "qwen-smoke"},
            "error": None,
        }

    monkeypatch.setattr(qwen_realtime_provider, "_execute_core_tool", fake_core)

    result = provider.test_tool_call()

    assert result.ok is True
    assert result.tool_name == "orion.test.ping"
    assert result.assistant_text == "Smoke passed"
    assert calls == [("call-42", "orion_test_ping", '{"message":"qwen-smoke"}')]

    user_item_indexes = [
        index
        for index, payload in enumerate(ws.sent)
        if payload.get("type") == "conversation.item.create"
        and isinstance(payload.get("item"), dict)
        and payload["item"].get("type") == "message"
        and payload["item"].get("role") == "user"
    ]
    response_create_indexes = [index for index, payload in enumerate(ws.sent) if payload.get("type") == "response.create"]
    assert user_item_indexes
    assert response_create_indexes
    assert user_item_indexes[0] < response_create_indexes[0]
    user_content = ws.sent[user_item_indexes[0]]["item"]["content"]
    assert isinstance(user_content, list)
    assert user_content[0]["type"] == "input_text"
    assert "ORION connectivity test" in user_content[0]["text"]

    assert any(
        payload.get("type") == "conversation.item.create"
        and isinstance(payload.get("item"), dict)
        and payload["item"].get("type") == "function_call_output"
        for payload in ws.sent
    )
    assert ws.closed is True


def test_tool_smoke_rejects_incomplete_function_call(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _FakeWebSocket(
        [
            {"type": "session.updated"},
            {"type": "response.function_call_arguments.done", "call_id": "", "name": "orion_test_ping", "arguments": "{}"},
        ]
    )
    provider = QwenRealtimeProvider(_config())
    monkeypatch.setattr(provider, "_connect", lambda: ws)

    result = provider.test_tool_call()

    assert result.ok is False
    assert "incomplete function call" in result.message


def test_unknown_provider_tool_is_not_mapped_to_core() -> None:
    result = qwen_realtime_provider._execute_core_tool(_config(), "call-x", "dangerous_tool", "{}")
    assert result["ok"] is False
    assert "not mapped" in result["error"]


def test_invalid_tool_arguments_do_not_reach_core(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fail_urlopen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal called
        called = True
        raise AssertionError("Core must not be called for invalid JSON")

    monkeypatch.setattr(qwen_realtime_provider.urllib.request, "urlopen", fail_urlopen)
    result = qwen_realtime_provider._execute_core_tool(_config(), "call-json", "orion_test_ping", "{")
    assert result["ok"] is False
    assert "Invalid tool arguments JSON" in result["error"]
    assert called is False
