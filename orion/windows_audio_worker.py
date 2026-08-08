from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, Field


class AudioWorkerState(StrEnum):
    IDLE = "idle"
    PLAYING = "playing"
    STOPPED = "stopped"
    FAILED = "failed"


class AudioDuckingPolicy(StrEnum):
    NONE = "none"
    MUSIC = "music"
    NON_RADIO = "non_radio"
    ALL = "all"


class AudioDevice(BaseModel):
    device_id: str = "default"
    name: str = "Windows default audio output"
    is_default: bool = True


class AudioPlaybackRequest(BaseModel):
    command_id: UUID
    audio_path: str = Field(min_length=1)
    output_device_id: str = "default"
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    duck_game_audio: bool = True
    ducking_policy: AudioDuckingPolicy = AudioDuckingPolicy.NONE
    radio_effect: bool = False


class AudioPlaybackStatus(BaseModel):
    state: AudioWorkerState
    command_id: UUID | None = None
    audio_path: str | None = None
    output_device_id: str = "default"
    ducking_policy: AudioDuckingPolicy = AudioDuckingPolicy.NONE
    radio_effect: bool = False
    message: str = ""


class WindowsAudioWorker:
    """Stateful contract for a Windows-side audio process.

    The FastAPI core never opens a Windows device itself. A local Windows worker can
    consume these requests and use SAPI/Media Foundation/another backend to render
    and play audio. Keeping device ownership outside the server avoids COM/threading
    issues and makes VR-headset routing replaceable.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._status = AudioPlaybackStatus(state=AudioWorkerState.IDLE)
        self._device = AudioDevice()

    def devices(self) -> list[AudioDevice]:
        return [self._device.model_copy(deep=True)]

    def select_device(self, device: AudioDevice) -> AudioDevice:
        with self._lock:
            self._device = device.model_copy(deep=True)
            return self._device.model_copy(deep=True)

    def play(self, request: AudioPlaybackRequest) -> AudioPlaybackStatus:
        path = Path(request.audio_path)
        if path.suffix.casefold() != ".wav":
            raise ValueError("Windows audio worker currently accepts WAV playback requests only")
        with self._lock:
            if self._status.state is AudioWorkerState.PLAYING:
                raise ValueError("Audio playback is already in progress")
            self._status = AudioPlaybackStatus(
                state=AudioWorkerState.PLAYING,
                command_id=request.command_id,
                audio_path=request.audio_path,
                output_device_id=request.output_device_id or self._device.device_id,
                ducking_policy=request.ducking_policy,
                radio_effect=request.radio_effect,
                message="Playback accepted by Windows audio worker",
            )
            return self._status.model_copy(deep=True)

    def stop(self, command_id: UUID | None = None) -> AudioPlaybackStatus:
        with self._lock:
            if self._status.state is not AudioWorkerState.PLAYING:
                return self._status.model_copy(deep=True)
            if command_id is not None and self._status.command_id != command_id:
                raise ValueError("Requested command is not the active playback")
            self._status.state = AudioWorkerState.STOPPED
            self._status.message = "Playback stopped"
            return self._status.model_copy(deep=True)

    def complete(self, command_id: UUID) -> AudioPlaybackStatus:
        with self._lock:
            if self._status.command_id != command_id:
                raise ValueError("Requested command is not the active playback")
            if self._status.state is not AudioWorkerState.PLAYING:
                raise ValueError("Audio playback is not active")
            self._status.state = AudioWorkerState.IDLE
            self._status.message = "Playback completed"
            return self._status.model_copy(deep=True)

    def status(self) -> AudioPlaybackStatus:
        with self._lock:
            return self._status.model_copy(deep=True)

    def reset(self) -> None:
        with self._lock:
            self._status = AudioPlaybackStatus(state=AudioWorkerState.IDLE)
            self._device = AudioDevice()


windows_audio_worker = WindowsAudioWorker()
