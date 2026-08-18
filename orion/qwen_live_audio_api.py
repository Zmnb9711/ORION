from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orion.qwen_live_audio_core import QwenLiveStartRequest, QwenLiveStatus, qwen_live_audio

router = APIRouter(prefix="/v1/realtime/qwen/live", tags=["Realtime Voice"])


@router.get("", response_model=QwenLiveStatus)
def status() -> QwenLiveStatus:
    return qwen_live_audio.status()


@router.post("/start", response_model=QwenLiveStatus)
def start(payload: QwenLiveStartRequest) -> QwenLiveStatus:
    try:
        return qwen_live_audio.start(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/stop", response_model=QwenLiveStatus)
def stop() -> QwenLiveStatus:
    return qwen_live_audio.stop()
