from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from orion.audio_device_config import AudioEndpointSelection, AudioEndpointState, audio_device_config
from orion.windows_audio_worker import AudioDevice, AudioPlaybackRequest, AudioPlaybackStatus, windows_audio_worker
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint, wasapi_endpoint_catalog


router = APIRouter(prefix="/v1/windows-audio", tags=["Windows Audio Worker"])


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
