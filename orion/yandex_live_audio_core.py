from __future__ import annotations

import asyncio
import queue
import threading
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from orion.audio_device_config import audio_device_config
from orion.portaudio_devices import (
    PortAudioEndpoint,
    enumerate_portaudio_endpoints,
    portaudio_extra_settings,
    resolve_portaudio_endpoint,
)
from orion.windows_wasapi_backend import WasapiDirection
from orion.realtime_audio_transport import RealtimePcmFormat
from orion.yandex_live_diagnostics import YandexLiveDiagnostics
from orion.yandex_realtime_session import YandexRealtimeSession
from orion.yandex_realtime_provider import (
    YANDEX_INPUT_RATE,
    YANDEX_OUTPUT_RATE,
    sanitize_yandex_error,
)

CHANNELS = 1
DTYPE = "int16"
BLOCK_MS = 20
INPUT_FRAMES = 882
PLAYBACK_SLICE_BYTES = 1764
WORKER_JOIN_TIMEOUT_S = 2.0
SHUTDOWN_TIMEOUT_S = 5.0


class UnsupportedAudioFormat(RuntimeError):
    pass


class YandexLiveState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    CONNECTED = "connected"
    STREAMING = "streaming"
    ERROR = "error"


class YandexLiveStartRequest(BaseModel):
    api_key: str = Field(min_length=1)
    folder_id: str = Field(min_length=1)


class YandexLiveStatus(BaseModel):
    state: YandexLiveState = YandexLiveState.STOPPED
    phase: str = "idle"
    message: str = "Yandex live audio is stopped"
    session_id: str | None = None
    input_name: str | None = None
    output_name: str | None = None
    input_rate: int | None = None
    output_rate: int | None = None
    input_chunks: int = 0
    output_chunks: int = 0
    provider_audio_bytes: int = 0
    slices_written: int = 0
    slices_removed: int = 0
    stale_slices_discarded: int = 0
    close_code: int | None = None
    clean_close: bool | None = None
    last_error: str | None = None


@dataclass(slots=True, frozen=True)
class ResolvedYandexAudio:
    input_endpoint: PortAudioEndpoint
    output_endpoint: PortAudioEndpoint
    input_extra_settings: object | None
    output_extra_settings: object | None


@dataclass(slots=True, frozen=True)
class PlaybackSlice:
    response_id: str
    epoch: int
    sequence: int
    pcm: bytes


def split_yandex_playback_pcm(pcm: bytes) -> tuple[bytes, ...]:
    if len(pcm) % 2:
        raise ValueError("Provider output PCM is not aligned to complete int16 frames")
    return tuple(
        pcm[offset : offset + PLAYBACK_SLICE_BYTES]
        for offset in range(0, len(pcm), PLAYBACK_SLICE_BYTES)
    )


class ResponsePlaybackQueue:
    """Response-scoped FIFO with epoch invalidation and exact-byte slices."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._queue: queue.Queue[PlaybackSlice | object] = queue.Queue()
        self._stop_token = object()
        self._epoch = 0
        self._active_response: str | None = None
        self._response_epochs: dict[str, int | None] = {}
        self._invalidated: set[str] = set()
        self._sequences: dict[str, int] = {}
        self.removed_slices = 0
        self.stale_slices = 0

    def response_created(self, response_id: str) -> int:
        with self._lock:
            self._epoch += 1
            self._active_response = response_id
            self._response_epochs[response_id] = self._epoch
            self._sequences[response_id] = 0
            return self._epoch

    def enqueue_delta(self, response_id: str, pcm: bytes) -> tuple[int, int]:
        slices = split_yandex_playback_pcm(pcm)
        with self._lock:
            epoch = self._response_epochs.get(response_id)
            if epoch is None or response_id in self._invalidated:
                self.stale_slices += len(slices)
                return 0, len(slices)
            first = self._sequences.get(response_id, 0) + 1
            self._sequences[response_id] = first + len(slices) - 1
            for offset, item in enumerate(slices):
                self._queue.put(PlaybackSlice(response_id, epoch, first + offset, item))
            return len(slices), 0

    def invalidate_active(self) -> tuple[str | None, int]:
        with self._lock:
            response_id = self._active_response
            # Provider completion and physical playback completion are distinct.
            # Invalidate every response epoch that could still own a queued or
            # already-committed slice, including a response.done-before-drain.
            for owned_response, epoch in tuple(self._response_epochs.items()):
                if epoch is not None:
                    self._invalidated.add(owned_response)
                    self._response_epochs[owned_response] = None
            self._active_response = None
            removed = self._remove_stale_locked()
            self.removed_slices += removed
            return response_id, removed

    def response_done(self, response_id: str) -> None:
        # Do not release physical playback ownership here. Valid queued PCM must
        # drain unless a later speech_started invalidates its response epoch.
        return

    def _remove_stale_locked(self) -> int:
        kept: list[PlaybackSlice | object] = []
        removed = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, PlaybackSlice) and self.is_current(item):
                kept.append(item)
            elif item is self._stop_token:
                kept.append(item)
            else:
                removed += 1
        for item in kept:
            self._queue.put(item)
        return removed

    def is_current(self, item: PlaybackSlice) -> bool:
        with self._lock:
            return (
                item.response_id not in self._invalidated
                and self._response_epochs.get(item.response_id) == item.epoch
            )

    def get(self, timeout: float = 0.1) -> PlaybackSlice | object:
        return self._queue.get(timeout=timeout)

    def stop(self) -> None:
        self._queue.put(self._stop_token)

    def is_stop(self, item: object) -> bool:
        return item is self._stop_token


class _DirectYandexPcmEndpoint:
    """Existing PortAudio behavior behind the narrow provider PCM boundary."""

    transport_id = "direct"
    pcm_format = RealtimePcmFormat()

    def __init__(
        self,
        service: "YandexLiveAudioService",
        audio: ResolvedYandexAudio,
        sd: Any,
        stop_event: threading.Event,
        diagnostics: YandexLiveDiagnostics,
    ) -> None:
        self.service = service
        self.audio = audio
        self.sd = sd
        self.stop_event = stop_event
        self.diagnostics = diagnostics
        self.capture_queue: queue.Queue[bytes] = queue.Queue()
        self.playback = ResponsePlaybackQueue()
        self.worker_error: queue.Queue[BaseException] = queue.Queue(maxsize=1)
        self._failure: BaseException | None = None
        self.capture_thread: threading.Thread | None = None
        self.playback_thread: threading.Thread | None = None

    def _fail(self, exc: BaseException) -> None:
        self._failure = exc
        try:
            self.worker_error.put_nowait(exc)
        except queue.Full:
            pass
        self.stop_event.set()

    def start(self) -> None:
        self.capture_thread = threading.Thread(
            target=self._capture_worker,
            name="orion-yandex-capture",
            daemon=True,
        )
        self.playback_thread = threading.Thread(
            target=self._playback_worker,
            name="orion-yandex-playback",
            daemon=True,
        )
        self.capture_thread.start()
        self.playback_thread.start()

    def _capture_worker(self) -> None:
        try:
            with self.sd.RawInputStream(
                samplerate=YANDEX_INPUT_RATE,
                blocksize=INPUT_FRAMES,
                device=self.audio.input_endpoint.device_index,
                channels=CHANNELS,
                dtype=DTYPE,
                extra_settings=self.audio.input_extra_settings,
            ) as stream:
                while not self.stop_event.is_set():
                    pcm, overflowed = stream.read(INPUT_FRAMES)
                    if overflowed:
                        self.diagnostics.record("capture_overflow")
                    self.capture_queue.put(bytes(pcm))
                    status = self.service.status()
                    self.service._set(input_chunks=status.input_chunks + 1, phase="listening")
        except BaseException as exc:
            self._fail(exc)

    def _playback_worker(self) -> None:
        try:
            with self.sd.RawOutputStream(
                samplerate=YANDEX_OUTPUT_RATE,
                blocksize=INPUT_FRAMES,
                device=self.audio.output_endpoint.device_index,
                channels=CHANNELS,
                dtype=DTYPE,
                extra_settings=self.audio.output_extra_settings,
            ) as stream:
                while not self.stop_event.is_set():
                    try:
                        item = self.playback.get()
                    except queue.Empty:
                        continue
                    if self.playback.is_stop(item):
                        return
                    assert isinstance(item, PlaybackSlice)
                    if not self.playback.is_current(item):
                        status = self.service.status()
                        self.service._set(
                            stale_slices_discarded=status.stale_slices_discarded + 1
                        )
                        continue
                    stream.write(item.pcm)
                    status = self.service.status()
                    self.service._set(
                        output_chunks=status.output_chunks + 1,
                        slices_written=status.slices_written + 1,
                        phase="speaking",
                    )
        except BaseException as exc:
            self._fail(exc)

    def read_input(self, timeout: float = 0.1) -> bytes | None:
        if not self.worker_error.empty():
            raise self.worker_error.get_nowait()
        try:
            return self.capture_queue.get(timeout=timeout)
        except queue.Empty:
            if not self.worker_error.empty():
                raise self.worker_error.get_nowait()
            return None

    def failure(self) -> BaseException | None:
        return self._failure

    def input_speech_started(self) -> None:
        response_id, removed = self.playback.invalidate_active()
        status = self.service.status()
        self.service._set(slices_removed=status.slices_removed + removed)
        self.diagnostics.record(
            "direct_barge_in",
            response_id=response_id,
            slices_removed=removed,
        )

    def response_started(self, response_id: str) -> None:
        epoch = self.playback.response_created(response_id)
        self.diagnostics.record("direct_response_created", response_id=response_id, epoch=epoch)

    def response_audio(self, response_id: str, pcm16le: bytes) -> None:
        queued, stale = self.playback.enqueue_delta(response_id, pcm16le)
        status = self.service.status()
        self.service._set(
            provider_audio_bytes=status.provider_audio_bytes + len(pcm16le),
            stale_slices_discarded=status.stale_slices_discarded + stale,
        )
        self.diagnostics.record(
            "direct_audio_delta",
            response_id=response_id,
            byte_count=len(pcm16le),
            slices_queued=queued,
            stale_slices=stale,
        )

    def response_audio_done(self, response_id: str) -> None:
        self.diagnostics.record("direct_audio_done", response_id=response_id)

    def response_done(self, response_id: str, status: str) -> None:
        self.playback.response_done(response_id)
        self.diagnostics.record("direct_response_done", response_id=response_id, status=status)

    def stop(self) -> None:
        self.stop_event.set()
        self.playback.invalidate_active()
        self.playback.stop()
        for worker, name in (
            (self.capture_thread, "capture"),
            (self.playback_thread, "playback"),
        ):
            if worker is not None and worker.is_alive():
                worker.join(WORKER_JOIN_TIMEOUT_S)
            if worker is not None and worker.is_alive():
                self.diagnostics.record(f"{name}_worker_shutdown_timeout")


class YandexLiveAudioService:
    provider_id = "yandex"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = YandexLiveStatus()

    def status(self) -> YandexLiveStatus:
        with self._lock:
            return self._status.model_copy(deep=True)

    def _set(self, **changes: object) -> None:
        with self._lock:
            payload = self._status.model_dump()
            payload.update(changes)
            self._status = YandexLiveStatus.model_validate(payload)

    def start(self, request: YandexLiveStartRequest) -> YandexLiveStatus:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise ValueError("Yandex live audio is already running")
            self._stop = threading.Event()
            session_id = uuid.uuid4().hex
            self._status = YandexLiveStatus(
                state=YandexLiveState.STARTING,
                message="Starting Yandex live audio",
                session_id=session_id,
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(request, self._stop, session_id),
                name="orion-yandex-live",
                daemon=True,
            )
            self._thread.start()
            return self._status.model_copy(deep=True)

    def stop(self) -> YandexLiveStatus:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=SHUTDOWN_TIMEOUT_S + 1.0)
        with self._lock:
            if thread is not None and thread.is_alive():
                self._status.state = YandexLiveState.ERROR
                self._status.message = "Yandex live shutdown exceeded its bound"
                self._status.last_error = self._status.message
            else:
                self._status.state = YandexLiveState.STOPPED
                self._status.phase = "idle"
                self._status.message = "Yandex live audio stopped"
            return self._status.model_copy(deep=True)

    def _resolve_audio(self, sd: Any) -> ResolvedYandexAudio:
        state = audio_device_config.state()
        if state.resolved_input is None or state.resolved_output is None:
            raise RuntimeError(state.message or "ORION Core audio selection is not ready")
        endpoints = enumerate_portaudio_endpoints(sd)
        input_endpoint = resolve_portaudio_endpoint(
            endpoints,
            state.selection.input_device_id,
            WasapiDirection.INPUT,
            identity=state.selection.input_identity,
        )
        output_endpoint = resolve_portaudio_endpoint(
            endpoints,
            state.selection.output_device_id,
            WasapiDirection.OUTPUT,
            identity=state.selection.output_identity,
        )
        input_extra, _ = portaudio_extra_settings(sd, input_endpoint)
        output_extra, _ = portaudio_extra_settings(sd, output_endpoint)
        try:
            sd.check_input_settings(
                device=input_endpoint.device_index,
                channels=CHANNELS,
                dtype=DTYPE,
                samplerate=YANDEX_INPUT_RATE,
                extra_settings=input_extra,
            )
        except Exception as exc:
            raise UnsupportedAudioFormat(
                "UNSUPPORTED AUDIO FORMAT: selected input endpoint "
                f"#{input_endpoint.device_index} {input_endpoint.name} "
                f"[{input_endpoint.host_api_name}] does not accept mono PCM16 at 44100 Hz: {exc}"
            ) from exc
        try:
            sd.check_output_settings(
                device=output_endpoint.device_index,
                channels=CHANNELS,
                dtype=DTYPE,
                samplerate=YANDEX_OUTPUT_RATE,
                extra_settings=output_extra,
            )
        except Exception as exc:
            raise UnsupportedAudioFormat(
                "UNSUPPORTED AUDIO FORMAT: selected output endpoint "
                f"#{output_endpoint.device_index} {output_endpoint.name} "
                f"[{output_endpoint.host_api_name}] does not accept mono PCM16 at 44100 Hz: {exc}"
            ) from exc
        return ResolvedYandexAudio(input_endpoint, output_endpoint, input_extra, output_extra)

    def _run(self, request: YandexLiveStartRequest, stop_event: threading.Event, session_id: str) -> None:
        diagnostics = YandexLiveDiagnostics(session_id, request.api_key)
        try:
            import sounddevice as sd

            audio = self._resolve_audio(sd)
            self._set(
                input_name=f"{audio.input_endpoint.name} [{audio.input_endpoint.host_api_name}] (#{audio.input_endpoint.device_index})",
                output_name=f"{audio.output_endpoint.name} [{audio.output_endpoint.host_api_name}] (#{audio.output_endpoint.device_index})",
                input_rate=YANDEX_INPUT_RATE,
                output_rate=YANDEX_OUTPUT_RATE,
                message="Opening Yandex realtime session",
            )
            diagnostics.record(
                "audio_resolved",
                input_index=audio.input_endpoint.device_index,
                input_name=audio.input_endpoint.name,
                input_host_api=audio.input_endpoint.host_api_name,
                output_index=audio.output_endpoint.device_index,
                output_name=audio.output_endpoint.name,
                output_host_api=audio.output_endpoint.host_api_name,
                direct_rate=YANDEX_INPUT_RATE,
            )
            asyncio.run(self._run_async(request, audio, sd, stop_event, diagnostics))
        except Exception as exc:
            safe = sanitize_yandex_error(exc, request.api_key)
            diagnostics.record("session_error", error_type=type(exc).__name__, error=safe)
            self._set(
                state=YandexLiveState.ERROR,
                phase="idle",
                message=f"{type(exc).__name__}: {safe}",
                last_error=safe,
            )
        finally:
            stop_event.set()
            with self._lock:
                if self._status.state is not YandexLiveState.ERROR:
                    self._status.state = YandexLiveState.STOPPED
                    self._status.phase = "idle"
                    self._status.message = "Yandex live audio stopped"

    async def _run_async(
        self,
        request: YandexLiveStartRequest,
        audio: ResolvedYandexAudio,
        sd: Any,
        stop_event: threading.Event,
        diagnostics: YandexLiveDiagnostics,
    ) -> None:
        endpoint = _DirectYandexPcmEndpoint(self, audio, sd, stop_event, diagnostics)

        def streaming() -> None:
            self._set(
                state=YandexLiveState.STREAMING,
                message="Yandex live audio is running",
            )

        result = await YandexRealtimeSession(
            request.api_key,
            request.folder_id,
            endpoint,
            stop_event,
            diagnostics,
            on_streaming=streaming,
        ).run()
        self._set(close_code=result.close_code, clean_close=result.clean_close)


yandex_live_audio = YandexLiveAudioService()
