from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from orion.realtime_provider import RealtimeProviderState, RealtimeSmokeResult


@dataclass(slots=True, frozen=True)
class QwenRealtimeConfig:
    api_key: str
    workspace_id: str
    core_base_url: str = "http://127.0.0.1:8000"
    region: str = "singapore"
    model: str = "qwen3.5-omni-flash-realtime"
    timeout_s: float = 15.0


_REGION_HOSTS = {
    "singapore": "{workspace}.ap-southeast-1.maas.aliyuncs.com",
    "beijing": "{workspace}.cn-beijing.maas.aliyuncs.com",
}

_PROVIDER_TO_CORE_TOOL = {
    "orion_test_ping": "orion.test.ping",
}


def build_qwen_realtime_url(config: QwenRealtimeConfig) -> str:
    host_template = _REGION_HOSTS.get(config.region.casefold())
    if host_template is None:
        raise ValueError(f"Unsupported Qwen region: {config.region}")
    workspace = config.workspace_id.strip()
    if not workspace:
        raise ValueError("Qwen Workspace ID is required")
    model = config.model.strip()
    if not model:
        raise ValueError("Qwen realtime model is required")
    host = host_template.format(workspace=workspace)
    return f"wss://{host}/api-ws/v1/realtime?model={quote(model, safe='-_.')}"


def _tool_definition() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "orion_test_ping",
            "description": "Run the harmless ORION Core ADR-004 connectivity smoke test.",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    }


def _session_update(*, with_tool: bool) -> dict[str, Any]:
    session: dict[str, Any] = {
        "modalities": ["text"],
        "instructions": (
            "You are the ORION ADR-004 connectivity test. "
            "Do not claim a local action succeeded unless the tool result says it succeeded."
        ),
    }
    if with_tool:
        session["tools"] = [_tool_definition()]
        session["instructions"] += (
            " For this test, call orion_test_ping exactly once with message 'qwen-smoke' "
            "before producing a final answer."
        )
    return {"type": "session.update", "session": session}


def _tool_smoke_user_item() -> dict[str, Any]:
    """Seed the realtime conversation with an actual user turn.

    Qwen rejects response.create when the conversation contains no user-role
    message, even when session instructions explicitly request a tool call.
    """
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Run the ORION connectivity test now. Use the required test tool before answering.",
                }
            ],
        },
    }


def _execute_core_tool(config: QwenRealtimeConfig, call_id: str, provider_name: str, arguments: str) -> dict[str, Any]:
    core_name = _PROVIDER_TO_CORE_TOOL.get(provider_name)
    if core_name is None:
        return {
            "call_id": call_id,
            "name": provider_name,
            "ok": False,
            "output": {},
            "error": "Provider requested a tool that is not mapped into the ADR-004 smoke allowlist.",
        }
    try:
        parsed_arguments = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        return {
            "call_id": call_id,
            "name": core_name,
            "ok": False,
            "output": {},
            "error": f"Invalid tool arguments JSON: {exc}",
        }
    if not isinstance(parsed_arguments, dict):
        parsed_arguments = {}

    payload = json.dumps(
        {"call_id": call_id, "name": core_name, "arguments": parsed_arguments}, ensure_ascii=False
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.core_base_url.rstrip('/')}/v1/realtime/tools/execute",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=min(config.timeout_s, 5.0)) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {
            "call_id": call_id,
            "name": core_name,
            "ok": False,
            "output": {},
            "error": f"ORION Core tool call failed: {exc}",
        }
    return result if isinstance(result, dict) else {"ok": False, "output": {}, "error": "Invalid Core result"}


class QwenRealtimeProvider:
    """Qwen-specific adapter outside ORION Core.

    Phase-B implementation is deliberately text/tool only. Microphone capture,
    audio streaming and playback are added only after this vertical slice passes.
    """

    provider_id = "qwen_realtime"

    def __init__(self, config: QwenRealtimeConfig) -> None:
        self.config = config

    def _connect(self):  # noqa: ANN202
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("Qwen cloud realtime support is not installed") from exc
        if not self.config.api_key.strip():
            raise ValueError("Qwen API key is required")
        return websocket.create_connection(
            build_qwen_realtime_url(self.config),
            header=[f"Authorization: Bearer {self.config.api_key.strip()}", "User-Agent: ORION/0.2"],
            timeout=self.config.timeout_s,
            enable_multithread=True,
        )

    @staticmethod
    def _receive_json(ws) -> dict[str, Any]:  # noqa: ANN001
        raw = ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise RuntimeError("Qwen returned a non-object realtime event")
        return event

    @staticmethod
    def _error_message(event: dict[str, Any]) -> str:
        detail = event.get("error")
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("code") or detail)
        return str(detail or "Qwen realtime error")

    def test_connection(self) -> RealtimeSmokeResult:
        started = time.monotonic()
        ws = None
        try:
            ws = self._connect()
            ws.send(json.dumps(_session_update(with_tool=False)))
            deadline = time.monotonic() + self.config.timeout_s
            while time.monotonic() < deadline:
                event = self._receive_json(ws)
                event_type = event.get("type")
                if event_type == "session.updated":
                    return RealtimeSmokeResult(
                        ok=True,
                        provider=self.provider_id,
                        state=RealtimeProviderState.READY,
                        message="Qwen Realtime session is ready.",
                        latency_ms=(time.monotonic() - started) * 1000,
                    )
                if event_type == "error":
                    raise RuntimeError(self._error_message(event))
            raise TimeoutError("Timed out waiting for Qwen session.updated")
        except (OSError, ValueError, RuntimeError, TimeoutError, json.JSONDecodeError) as exc:
            return RealtimeSmokeResult(
                ok=False,
                provider=self.provider_id,
                state=RealtimeProviderState.ERROR,
                message=str(exc),
                latency_ms=(time.monotonic() - started) * 1000,
            )
        finally:
            if ws is not None:
                try:
                    ws.close()
                except OSError:
                    pass

    def test_tool_call(self) -> RealtimeSmokeResult:
        started = time.monotonic()
        ws = None
        tool_result: dict[str, Any] | None = None
        tool_name: str | None = None
        assistant_parts: list[str] = []
        followup_requested = False
        try:
            ws = self._connect()
            ws.send(json.dumps(_session_update(with_tool=True)))
            deadline = time.monotonic() + self.config.timeout_s
            session_ready = False
            while time.monotonic() < deadline:
                event = self._receive_json(ws)
                event_type = event.get("type")
                if event_type == "error":
                    raise RuntimeError(self._error_message(event))
                if event_type == "session.updated" and not session_ready:
                    session_ready = True
                    ws.send(json.dumps(_tool_smoke_user_item(), ensure_ascii=False))
                    ws.send(json.dumps({"type": "response.create", "response": {"modalities": ["text"]}}))
                    continue
                if event_type == "response.function_call_arguments.done":
                    call_id = str(event.get("call_id") or "")
                    provider_name = str(event.get("name") or "")
                    arguments = str(event.get("arguments") or "{}")
                    if not call_id or not provider_name:
                        raise RuntimeError("Qwen returned an incomplete function call")
                    tool_name = _PROVIDER_TO_CORE_TOOL.get(provider_name, provider_name)
                    tool_result = _execute_core_tool(self.config, call_id, provider_name, arguments)
                    ws.send(
                        json.dumps(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": json.dumps(tool_result, ensure_ascii=False),
                                },
                            },
                            ensure_ascii=False,
                        )
                    )
                    ws.send(json.dumps({"type": "response.create", "response": {"modalities": ["text"]}}))
                    followup_requested = True
                    continue
                if followup_requested and event_type == "response.text.delta":
                    assistant_parts.append(str(event.get("delta") or ""))
                    continue
                if followup_requested and event_type == "response.text.done":
                    text = event.get("text")
                    if isinstance(text, str) and text:
                        assistant_parts = [text]
                    continue
                if followup_requested and event_type == "response.done":
                    if tool_result is None:
                        raise RuntimeError("Qwen completed without executing the ORION smoke tool")
                    ok = bool(tool_result.get("ok"))
                    return RealtimeSmokeResult(
                        ok=ok,
                        provider=self.provider_id,
                        state=RealtimeProviderState.READY if ok else RealtimeProviderState.ERROR,
                        message="Qwen → ORION Core → test tool vertical slice passed." if ok else str(tool_result.get("error")),
                        tool_name=tool_name,
                        tool_output=tool_result.get("output") if isinstance(tool_result.get("output"), dict) else {},
                        assistant_text="".join(assistant_parts).strip() or None,
                        latency_ms=(time.monotonic() - started) * 1000,
                    )
            raise TimeoutError("Timed out waiting for the Qwen tool-call smoke test")
        except (OSError, ValueError, RuntimeError, TimeoutError, json.JSONDecodeError) as exc:
            return RealtimeSmokeResult(
                ok=False,
                provider=self.provider_id,
                state=RealtimeProviderState.ERROR,
                message=str(exc),
                tool_name=tool_name,
                tool_output=tool_result.get("output") if isinstance(tool_result, dict) and isinstance(tool_result.get("output"), dict) else None,
                assistant_text="".join(assistant_parts).strip() or None,
                latency_ms=(time.monotonic() - started) * 1000,
            )
        finally:
            if ws is not None:
                try:
                    ws.close()
                except OSError:
                    pass
