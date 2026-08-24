from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.qwen_live_audio_core import QwenLiveStartRequest, QwenLiveStatus, qwen_live_audio
from orion.realtime_live_core import RealtimeLiveStartRequest, realtime_live
from orion.realtime_provider import RealtimeLiveStatus
from orion.realtime_tools import RealtimeToolCall, RealtimeToolResult, realtime_tools
from orion.yandex_realtime_provider import YandexRealtimeConfig, YandexRealtimeProvider

router = APIRouter(prefix="/v1/realtime", tags=["Realtime Voice"])


class YandexConnectionTestRequest(BaseModel):
    api_key: str = Field(min_length=1)
    folder_id: str = Field(min_length=1)


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
        realtime_live.start(
            RealtimeLiveStartRequest(
                provider="qwen",
                **payload.model_dump(),
            )
        )
        return qwen_live_audio.status()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/qwen/live/stop", response_model=QwenLiveStatus)
def qwen_live_stop() -> QwenLiveStatus:
    realtime_live.stop("qwen")
    return qwen_live_audio.status()


@router.get("/live/status", response_model=RealtimeLiveStatus)
def realtime_live_status() -> RealtimeLiveStatus:
    return realtime_live.status()


@router.post("/live/start", response_model=RealtimeLiveStatus)
def realtime_live_start(payload: RealtimeLiveStartRequest) -> RealtimeLiveStatus:
    try:
        return realtime_live.start(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/live/stop", response_model=RealtimeLiveStatus)
def realtime_live_stop() -> RealtimeLiveStatus:
    return realtime_live.stop()


@router.post("/yandex/test-connection")
def yandex_test_connection(payload: YandexConnectionTestRequest) -> dict[str, object]:
    result = YandexRealtimeProvider(
        YandexRealtimeConfig(api_key=payload.api_key, folder_id=payload.folder_id)
    ).test_connection()
    return {
        "ok": result.ok,
        "provider": result.provider,
        "state": result.state,
        "message": result.message,
        "latency_ms": result.latency_ms,
    }
