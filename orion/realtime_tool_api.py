from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from orion.qwen_live_audio_core import QwenLiveStartRequest, QwenLiveStatus, qwen_live_audio
from orion.realtime_tools import RealtimeToolCall, RealtimeToolResult, realtime_tools

router = APIRouter(prefix="/v1/realtime", tags=["Realtime Voice"])


@router.get("/tools")
def list_realtime_tools() -> dict[str, list[dict[str, Any]]]:
    """Expose only Core-owned tools admitted to realtime voice."""

    return {"tools": realtime_tools.definitions()}


@router.post("/tools/execute", response_model=RealtimeToolResult)
def execute_realtime_tool(call: RealtimeToolCall) -> RealtimeToolResult:
    """Execute the Core-owned allowlist with live context/capability gates."""

    return realtime_tools.execute(call)


@router.get("/qwen/live", response_model=QwenLiveStatus)
def qwen_live_status() -> QwenLiveStatus:
    """Return the state of the Core-owned Qwen speech-to-speech session."""

    return qwen_live_audio.status()


@router.post("/qwen/live/start", response_model=QwenLiveStatus)
def qwen_live_start(payload: QwenLiveStartRequest) -> QwenLiveStatus:
    """Start microphone -> Qwen -> selected-output inside ORION Core.

    The API key crosses localhost once and remains memory-only; it is never
    written to ORION configuration or diagnostic files.
    """

    try:
        return qwen_live_audio.start(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/qwen/live/stop", response_model=QwenLiveStatus)
def qwen_live_stop() -> QwenLiveStatus:
    return qwen_live_audio.stop()
