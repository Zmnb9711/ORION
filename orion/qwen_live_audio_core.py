from __future__ import annotations

import base64
import json
import threading
import time
from array import array
from dataclasses import dataclass
from enum import StrEnum
from queue import Empty, SimpleQueue
from typing import Any

from pydantic import BaseModel, Field

from orion.audio_device_config import audio_device_config
from orion.qwen_realtime_provider import QwenRealtimeConfig, QwenRealtimeProvider
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint

QWEN_INPUT_RATE = 16_000
QWEN_OUTPUT_RATE = 24_000
CHANNELS = 1
CAPTURE_MS = 40


class QwenLiveState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    CONNECTED = "connected"
    STREAMING = "streaming"
    ERROR = "error"


class QwenAudioPhase(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    SPEAKING = "speaking"


class QwenLiveStartRequest(BaseModel):
    api_key: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    region: str = "singapore"
    model: str = "qwen3.5-omni-flash-realtime"
    voice: str = "Tina"


class QwenLiveStatus(BaseModel):
    state: QwenLiveState = QwenLiveState.STOPPED
    phase: QwenAudioPhase = QwenAudioPhase.IDLE
    message: str = "Qwen live audio is stopped"
    input_name: str | None = None
    output_name: str | None = None
    input_native_rate: int | None = None
    output_native_rate: int | None = None
    input_chunks: int = 0
    output_chunks: int = 0
    transcript: str = ""


@dataclass(slots=True)
class _ResolvedAudio:
    input_endpoint: WasapiEndpoint
    output_endpoint: WasapiEndpoint
    input_index: int
    output_index: int
    native_rate: int


def _resample_pcm16_mono(data: bytes, source_rate: int, target_rate: int) -> bytes:
    if not data or source_rate == target_rate:
        return data
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("PCM sample rates must be positive")
    samples = array("h")
    samples.frombytes(data)
    if len(samples) < 2:
        return data
    target_count = max(1, round(len(samples) * target_rate / source_rate))
    if target_count == 1:
        return array("h", [samples[0]]).tobytes()
    scale = (len(samples) - 1) / (target_count - 1)
    output = array("h")
    for index in range(target_count):
        position = index * scale
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        fraction = position - left
        value = round(samples[left] + (samples[right] - samples[left]) * fraction)
        output.append(max(-32768, min(32767, value)))
    return output.tobytes()


def _audio_session_update(model: str, voice: str) -> dict[str, Any]:
    normalized = model.strip().casefold()
    vad_type = "semantic_vad" if normalized == "qwen3.5-omni-realtime" or normalized.startswith("qwen3.5-omni-realtime-") else "server_vad"
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "voice": voice,
            "instructions": (
                "You are ORION's realtime conversational voice. "
                "Understand Russian speech and always answer in Russian. "
                "Do not answer in Chinese. Change language only if the user explicitly asks you to."
            ),
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "turn_detection": {"type": vad_type, "threshold": 0.5, "silence_duration_ms": 800},
        },
    }


class QwenLiveAudioService:
    """Qwen realtime speech-to-speech using one PortAudio full-duplex stream."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = QwenLiveStatus()

    def status(self) -> QwenLiveStatus:
        with self._lock:
            return self._status.model_copy(deep=True)

    def start(self, request: QwenLiveStartRequest) -> QwenLiveStatus:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise ValueError("Qwen live audio is already running")
            self._stop = threading.Event()
            self._status = QwenLiveStatus(state=QwenLiveState.STARTING, message="Starting Qwen live audio")
            self._thread = threading.Thread(target=self._run, args=(request, self._stop), daemon=True, name="orion-qwen-live")
            self._thread.start()
            return self._status.model_copy(deep=True)

    def stop(self) -> QwenLiveStatus:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        with self._lock:
            if self._status.state is not QwenLiveState.ERROR:
                self._status = QwenLiveStatus(message="Qwen live audio stopped")
            return self._status.model_copy(deep=True)

    def _set(self, **changes: Any) -> None:
        with self._lock:
            payload = self._status.model_dump()
            payload.update(changes)
            self._status = QwenLiveStatus.model_validate(payload)

    @staticmethod
    def _resolve_device(sd: Any, endpoint: WasapiEndpoint, direction: WasapiDirection) -> int:
        hostapis = list(sd.query_hostapis())
        devices = list(sd.query_devices())
        wasapi_hosts = {i for i, item in enumerate(hostapis) if "wasapi" in str(item.get("name", "")).casefold()}
        channel_key = "max_input_channels" if direction is WasapiDirection.INPUT else "max_output_channels"
        target = endpoint.name.casefold()
        candidates = [(i, str(item.get("name", ""))) for i, item in enumerate(devices)
                      if int(item.get(channel_key, 0)) > 0 and (not wasapi_hosts or int(item.get("hostapi", -1)) in wasapi_hosts)]
        exact = next((i for i, name in candidates if name.casefold() == target), None)
        if exact is not None:
            return exact
        partial = next((i for i, name in candidates if target in name.casefold() or name.casefold() in target), None)
        if partial is not None:
            return partial
        raise RuntimeError(f"Selected WASAPI {direction.value} endpoint is unavailable: {endpoint.name}")

    @staticmethod
    def _native_rate(sd: Any, index: int, fallback: int = 48_000) -> int:
        try:
            return max(1, int(round(float(sd.query_devices(index).get("default_samplerate", fallback)))))
        except (TypeError, ValueError):
            return fallback

    def _resolve_audio(self, sd: Any) -> _ResolvedAudio:
        state = audio_device_config.state()
        if state.resolved_input is None or state.resolved_output is None:
            raise RuntimeError("ORION Core audio input/output selection is not ready")
        input_index = self._resolve_device(sd, state.resolved_input, WasapiDirection.INPUT)
        output_index = self._resolve_device(sd, state.resolved_output, WasapiDirection.OUTPUT)
        input_rate = self._native_rate(sd, input_index)
        output_rate = self._native_rate(sd, output_index)
        # PortAudio full duplex has one stream sample rate. Prefer the Windows mix
        # rate when both endpoints agree; otherwise 48 kHz is the shared-mode norm.
        native_rate = input_rate if input_rate == output_rate else 48_000
        return _ResolvedAudio(state.resolved_input, state.resolved_output, input_index, output_index, native_rate)

    def _run(self, request: QwenLiveStartRequest, stop_event: threading.Event) -> None:
        ws = None
        try:
            import sounddevice as sd
            import websocket

            audio = self._resolve_audio(sd)
            self._set(message="Opening Qwen realtime session", input_name=audio.input_endpoint.name,
                      output_name=audio.output_endpoint.name, input_native_rate=audio.native_rate,
                      output_native_rate=audio.native_rate)
            config = QwenRealtimeConfig(api_key=request.api_key, workspace_id=request.workspace_id,
                                        region=request.region, model=request.model, timeout_s=15.0)
            provider = QwenRealtimeProvider(config)
            ws = provider._connect()
            ws.settimeout(0.25)
            ws.send(json.dumps(_audio_session_update(request.model, request.voice), ensure_ascii=False))
            deadline = time.monotonic() + config.timeout_s
            while time.monotonic() < deadline and not stop_event.is_set():
                try:
                    event = provider._receive_json(ws)
                except websocket.WebSocketTimeoutException:
                    continue
                if event.get("type") == "error":
                    raise RuntimeError(provider._error_message(event))
                if event.get("type") == "session.updated":
                    break
            else:
                raise TimeoutError("Timed out waiting for Qwen session.updated")

            frames = max(1, round(audio.native_rate * CAPTURE_MS / 1000))
            settings = sd.WasapiSettings(exclusive=False)
            self._set(state=QwenLiveState.CONNECTED, message="Qwen connected; opening one full-duplex WASAPI stream")

            capture_queue: SimpleQueue[bytes] = SimpleQueue()
            playback_queue: SimpleQueue[bytes] = SimpleQueue()
            playback_pending = bytearray()

            def audio_callback(indata: Any, outdata: Any, frame_count: int, time_info: Any, status: Any) -> None:
                del frame_count, time_info, status
                capture_queue.put(bytes(indata))

                bytes_needed = len(outdata)
                while len(playback_pending) < bytes_needed:
                    try:
                        playback_pending.extend(playback_queue.get_nowait())
                    except Empty:
                        break

                if playback_pending:
                    available = min(bytes_needed, len(playback_pending))
                    outdata[:available] = playback_pending[:available]
                    del playback_pending[:available]
                    if available < bytes_needed:
                        outdata[available:] = b"\x00" * (bytes_needed - available)
                    with self._lock:
                        self._status.output_chunks += 1
                else:
                    outdata[:] = b"\x00" * bytes_needed

            # Keep one PortAudio full-duplex stream, but let PortAudio schedule playback
            # continuously. Qwen audio deltas go straight to the transport playback queue
            # instead of waiting for ORION's capture/WebSocket loop to call stream.write().
            with sd.RawStream(samplerate=audio.native_rate, blocksize=frames,
                              device=(audio.input_index, audio.output_index), channels=(CHANNELS, CHANNELS),
                              dtype=("int16", "int16"), extra_settings=(settings, settings),
                              callback=audio_callback):
                self._set(state=QwenLiveState.STREAMING, phase=QwenAudioPhase.LISTENING,
                          message="Qwen live audio streaming through direct callback playback")
                while not stop_event.is_set():
                    try:
                        raw = capture_queue.get_nowait()
                    except Empty:
                        raw = b""

                    if raw:
                        qwen_pcm = _resample_pcm16_mono(raw, audio.native_rate, QWEN_INPUT_RATE)
                        ws.send(json.dumps({"type": "input_audio_buffer.append",
                                            "audio": base64.b64encode(qwen_pcm).decode("ascii")}))
                        with self._lock:
                            self._status.input_chunks += 1

                    try:
                        event = provider._receive_json(ws)
                    except websocket.WebSocketTimeoutException:
                        continue
                    event_type = str(event.get("type") or "")
                    if event_type == "error":
                        raise RuntimeError(provider._error_message(event))
                    if event_type == "response.audio.delta" and isinstance(event.get("delta"), str):
                        playback_queue.put(
                            _resample_pcm16_mono(
                                base64.b64decode(event["delta"]),
                                QWEN_OUTPUT_RATE,
                                audio.native_rate,
                            )
                        )
                        self._set(phase=QwenAudioPhase.SPEAKING, message="Qwen speaking")
                    elif event_type in {"response.audio.done", "response.done"}:
                        self._set(phase=QwenAudioPhase.LISTENING, message="Qwen listening")
                    elif event_type in {"response.audio_transcript.delta", "conversation.item.input_audio_transcription.delta"}:
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            with self._lock:
                                self._status.transcript = (self._status.transcript + delta)[-4000:]

        except Exception as exc:
            self._set(state=QwenLiveState.ERROR, phase=QwenAudioPhase.IDLE, message=f"{type(exc).__name__}: {exc}")
        finally:
            stop_event.set()
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
            with self._lock:
                if self._status.state is not QwenLiveState.ERROR:
                    self._status.state = QwenLiveState.STOPPED
                    self._status.phase = QwenAudioPhase.IDLE
                    self._status.message = "Qwen live audio stopped"


qwen_live_audio = QwenLiveAudioService()
