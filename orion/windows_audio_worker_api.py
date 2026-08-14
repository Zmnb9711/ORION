from __future__ import annotations

import threading
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orion.audio_conversation_test import ConversationalAudioTestResult, run_conversational_audio_test
from orion.audio_device_config import AudioEndpointSelection, AudioEndpointState, audio_device_config
from orion.whisper_cpp_stt import WHISPER_MODEL_NAME, ensure_runtime, runtime_ready
from orion.windows_audio_worker import AudioDevice, AudioPlaybackRequest, AudioPlaybackStatus, windows_audio_worker
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint, wasapi_endpoint_catalog


router = APIRouter(prefix="/v1/windows-audio", tags=["Windows Audio Worker"])


class SttProvisionStatus(BaseModel):
    ready: bool
    running: bool
    model: str = WHISPER_MODEL_NAME
    stage: str = "not_installed"
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    percent: float | None = None
    error: str = ""


_stt_lock = threading.RLock()
_stt_status = SttProvisionStatus(ready=False, running=False)


def _stt_snapshot() -> SttProvisionStatus:
    with _stt_lock:
        status = _stt_status.model_copy(deep=True)
    if runtime_ready() and not status.running:
        status.ready = True
        status.stage = "ready"
        status.error = ""
        status.percent = 100.0
    return status


def _set_stt_status(**updates) -> None:
    global _stt_status
    with _stt_lock:
        _stt_status = _stt_status.model_copy(update=updates)


def _stt_progress(stage: str, downloaded: int, total: int | None) -> None:
    percent = None
    if total and total > 0:
        percent = max(0.0, min(100.0, downloaded * 100.0 / total))
    _set_stt_status(
        ready=stage == "ready",
        running=stage != "ready",
        stage=stage,
        downloaded_bytes=downloaded,
        total_bytes=total,
        percent=100.0 if stage == "ready" else percent,
        error="",
    )


def _prepare_stt_worker() -> None:
    try:
        ensure_runtime(progress=_stt_progress)
    except Exception as exc:
        _set_stt_status(
            ready=False,
            running=False,
            stage="failed",
            error=f"{type(exc).__name__}: {exc}",
        )


@router.get("/devices", response_model=list[AudioDevice])
def list_audio_devices() -> list[AudioDevice]:
    return windows_audio_worker.devices()


@router.get("/wasapi/endpoints", response_model=list[WasapiEndpoint])
def list_wasapi_endpoints() -> list[WasapiEndpoint]:
    return wasapi_endpoint_catalog.endpoints()


@router.get("/wasapi/inputs", response_model=list[WasapiEndpoint])
def list_wasapi_inputs() -> list[WasapiEndpoint]:
    return wasapi_endpoint_catalog.endpoints(WasapiDirection.INPUT)


@router.get("/wasapi/outputs", response_model=list[WasapiEndpoint])
def list_wasapi_outputs() -> list[WasapiEndpoint]:
    return wasapi_endpoint_catalog.endpoints(WasapiDirection.OUTPUT)


@router.get("/wasapi/vr-candidates", response_model=list[WasapiEndpoint])
def list_wasapi_vr_candidates() -> list[WasapiEndpoint]:
    return wasapi_endpoint_catalog.vr_candidates()


@router.get("/selection", response_model=AudioEndpointState)
def get_audio_selection() -> AudioEndpointState:
    return audio_device_config.state()


@router.put("/selection", response_model=AudioEndpointState)
def set_audio_selection(selection: AudioEndpointSelection) -> AudioEndpointState:
    try:
        return audio_device_config.select(selection)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/selection/reset", response_model=AudioEndpointState)
def reset_audio_selection() -> AudioEndpointState:
    return audio_device_config.reset()


@router.get("/stt/status", response_model=SttProvisionStatus)
def stt_status() -> SttProvisionStatus:
    return _stt_snapshot()


@router.post("/stt/prepare", response_model=SttProvisionStatus)
def prepare_stt() -> SttProvisionStatus:
    current = _stt_snapshot()
    if current.ready or current.running:
        return current
    _set_stt_status(
        ready=False,
        running=True,
        stage="starting",
        downloaded_bytes=0,
        total_bytes=None,
        percent=None,
        error="",
    )
    threading.Thread(target=_prepare_stt_worker, name="orion-whisper-prepare", daemon=True).start()
    return _stt_snapshot()


@router.post("/test/conversation", response_model=ConversationalAudioTestResult)
def conversation_audio_test() -> ConversationalAudioTestResult:
    if not runtime_ready():
        return ConversationalAudioTestResult(
            ok=False,
            stages={
                "core_connected": True,
                "input_resolved": False,
                "audio_captured": False,
                "phrase_recognized": False,
                "output_resolved": False,
                "response_played": False,
            },
            message="Whisper medium is not prepared. Use Prepare Speech Recognition in Launcher first.",
        )
    try:
        return run_conversational_audio_test()
    except Exception as exc:
        return ConversationalAudioTestResult(
            ok=False,
            stages={
                "core_connected": True,
                "input_resolved": False,
                "audio_captured": False,
                "phrase_recognized": False,
                "output_resolved": False,
                "response_played": False,
            },
            message=f"Audio test failed inside Core: {exc}",
        )


@router.put("/device", response_model=AudioDevice)
def select_audio_device(device: AudioDevice) -> AudioDevice:
    return windows_audio_worker.select_device(device)


@router.get("/status", response_model=AudioPlaybackStatus)
def audio_status() -> AudioPlaybackStatus:
    return windows_audio_worker.status()


@router.post("/play", response_model=AudioPlaybackStatus)
def play_audio(request: AudioPlaybackRequest) -> AudioPlaybackStatus:
    try:
        return windows_audio_worker.play(request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/stop", response_model=AudioPlaybackStatus)
def stop_audio(command_id: UUID | None = None) -> AudioPlaybackStatus:
    try:
        return windows_audio_worker.stop(command_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{command_id}/complete", response_model=AudioPlaybackStatus)
def complete_audio(command_id: UUID) -> AudioPlaybackStatus:
    try:
        return windows_audio_worker.complete(command_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
