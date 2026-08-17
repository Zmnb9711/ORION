from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/realtime", tags=["Realtime Voice"])


class RealtimeToolCall(BaseModel):
    """Provider-neutral request to execute one ORION tool locally."""

    call_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)


class RealtimeToolResult(BaseModel):
    """Provider-neutral result returned to whichever realtime provider is active."""

    call_id: str
    name: str
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


def _test_ping(arguments: dict[str, Any]) -> dict[str, Any]:
    message = arguments.get("message")
    return {
        "status": "ok",
        "tool": "orion.test.ping",
        "message": "pong" if message is None else str(message),
    }


_TEST_TOOLS = {
    "orion.test.ping": _test_ping,
}


@router.get("/tools")
def list_realtime_tools() -> dict[str, list[dict[str, Any]]]:
    """Expose only tools explicitly admitted to the ADR-004 smoke gate."""

    return {
        "tools": [
            {
                "name": "orion.test.ping",
                "description": "Harmless deterministic ORION Core connectivity smoke tool.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            }
        ]
    }


@router.post("/tools/execute", response_model=RealtimeToolResult)
def execute_realtime_tool(call: RealtimeToolCall) -> RealtimeToolResult:
    """Execute only the deterministic smoke-tool allowlist.

    ATC/AWACS/JTAC/AAR and mission-control tools are deliberately not exposed
    until ADR-004's cloud vertical slice has passed its real-machine gate.
    """

    handler = _TEST_TOOLS.get(call.name)
    if handler is None:
        return RealtimeToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=False,
            error="Tool is not enabled for the ADR-004 realtime smoke gate.",
        )
    try:
        output = handler(call.arguments)
    except (TypeError, ValueError) as exc:
        return RealtimeToolResult(call_id=call.call_id, name=call.name, ok=False, error=str(exc))
    return RealtimeToolResult(call_id=call.call_id, name=call.name, ok=True, output=output)
