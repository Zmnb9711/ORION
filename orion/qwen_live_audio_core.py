from __future__ import annotations

import base64
import json
import threading
import time
from array import array
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from orion.audio_device_config import audio_device_config
from orion.qwen_realtime_provider import QwenRealtimeConfig, QwenRealtimeProvider
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint

QWEN_INPUT_RATE = 16_000
QWEN_OUTPUT_RATE = 24_000
CHANNELS = 1
SAMPLE_WIDTH = 2
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
    input_rate: int
    output_rate: int


class _HalfDuplexGate:
    """Automatic microphone gate for the stable Windows phase-1 voice path."""

    def __init__(self) -> None:
        self._capture_allowed = threading.Event()
        self._capture_allowed.set()
        self.phase = QwenAudioPhase.LISTENING

    def begin_playback(self) -> None:
        self._capture_allowed.clear()
        self.phase = QwenAudioPhase.SPEAKING

    def end_playback(self) -> None:
        self.phase = QwenAudioPhase.LISTENING
        self._capture_allowed.set()

    def can_capture(self) -> bool:
        return self._capture_allowed.is_set()


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
                "You are ORION's realtime conversational voice. Talk naturally in the language used by the user. "
                "This clean ADR-004 phase is conversation only. Do not claim control of DCS, ATC, AWACS, JTAC or AAR."
            ),
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "turn_detection": {
                "type": vad_type,
                "threshold": 0.5,
                "silence_duration_ms": 800,
            },
        },
    }


class QwenLiveAudioService:
    """Core-owned Qwen speech-to-speech session.

    Audio capture deliberately runs in ORION Core, the same process that owns and
    already validates the selected Windows endpoints. This avoids reusing
    process-local PortAudio indices in Launcher and keeps one canonical audio path.
    The API key lives only in the in-memory start request and is never persisted.
    """

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
            self._status = QwenLiveStatus(state=QwenLiveState.STARTING, message="Starting Qwen live audio in Core")
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
                self._status.state = QwenLiveState.STOPPED
                self._status.phase = QwenAudioPhase.IDLE
                self._status.message = "Qwen live audio stopped"
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
        wasapi_hosts = {index for index, item in enumerate(hostapis) if "wasapi" in str(item.get("name", "")).casefold()}
        channel_key = "max_input_channels" if direction is WasapiDirection.INPUT else "max_output_channels"
        target = endpoint.name.casefold()
        candidates: list[tuple[int, str]] = []
        for index, item in enumerate(devices):
            if int(item.get(channel_key, 0)) <= 0:
                continue
            if wasapi_hosts and int(item.get("hostapi", -1)) not in wasapi_hosts:
                continue
            candidates.append((index, str(item.get("name", ""))))
        exact = next((index for index, name in candidates if name.casefold() == target), None)
        if exact is not None:
            return exact
        partial = next((index for index, name in candidates if target in name.casefold() or name.casefold() in target), None)
        if partial is not None:
            return partial
        raise RuntimeError(f"Selected WASAPI {direction.value} endpoint is unavailable: {endpoint.name}")

    @staticmethod
    def _native_rate(sd: Any, index: int, fallback: int = 48_000) -> int:
        info = sd.query_devices(index)
        try:
            value = int(round(float(info.get("default_samplerate", fallback))))
        except (TypeError, ValueError):
            value = fallback
        return value if value > 0 else fallback

    def _resolve_audio(self, sd: Any) -> _ResolvedAudio:
        state = audio_device_config.state()
        if state.resolved_input is None or state.resolved_output is None:
            raise RuntimeError("ORION Core audio input/output selection is not ready")
        input_index = self._resolve_device(sd, state.resolved_input, WasapiDirection.INPUT)
        output_index = self._resolve_device(sd, state.resolved_output, WasapiDirection.OUTPUT)
        return _ResolvedAudio(
            input_endpoint=state.resolved_input,
            output_endpoint=state.resolved_output,
            input_index=input_index,
            output_index=output_index,
            input_rate=self._native_rate(sd, input_index),
            output_rate=self._native_rate(sd, output_index),
        )

    def _run(self, request: QwenLiveStartRequest, stop_event: threading.Event) -> None:
        ws = None
        capture_thread: threading.Thread | None = None
        try:
            import sounddevice as sd
            import websocket

            audio = self._resolve_audio(sd)
            self._set(
                message="Opening Qwen realtime session",
                input_name=audio.input_endpoint.name,
                output_name=audio.output_endpoint.name,
                input_native_rate=audio.input_rate,
                output_native_rate=audio.output_rate,
            )
            config = QwenRealtimeConfig(
                api_key=request.api_key,
                workspace_id=request.workspace_id,
                region=request.region,
                model=request.model,
                timeout_s=15.0,
            )
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

            self._set(state=QwenLiveState.CONNECTED, message="Qwen connected; opening Core-owned audio streams")
            capture_error: list[BaseException] = []
            gate = _HalfDuplexGate()

            # Match the already field-proven Core microphone test: open a blocking
            # RawInputStream in shared WASAPI and read frames. No callback/start()
            # path and no Launcher-side PortAudio index is involved.
            input_frames = max(1, round(audio.input_rate * CAPTURE_MS / 1000))
            output_settings = sd.WasapiSettings(exclusive=False)
            input_settings = sd.WasapiSettings(exclusive=False)

            with sd.RawInputStream(
                samplerate=audio.input_rate,
                blocksize=input_frames,
                device=audio.input_index,
                channels=CHANNELS,
                dtype="int16",
                extra_settings=input_settings,
            ) as mic, sd.RawOutputStream(
                samplerate=audio.output_rate,
                device=audio.output_index,
                channels=CHANNELS,
                dtype="int16",
                extra_settings=output_settings,
            ) as speaker:
                self._set(
                    state=QwenLiveState.STREAMING,
                    phase=QwenAudioPhase.LISTENING,
                    message="Qwen live audio listening through ORION Core",
                )

                def capture() -> None:
                    try:
                        while not stop_event.is_set():
                            if not gate.can_capture():
                                time.sleep(0.01)
                                continue
                            raw, _overflowed = mic.read(input_frames)
                            # Playback can begin while a blocking read is in flight.
                            # Re-check the gate and discard that frame instead of
                            # echoing Qwen's own voice back into the cloud session.
                            if not gate.can_capture():
                                continue
                            qwen_pcm = _resample_pcm16_mono(bytes(raw), audio.input_rate, QWEN_INPUT_RATE)
                            ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(qwen_pcm).decode("ascii")}))
                            with self._lock:
                                self._status.input_chunks += 1
                    except BaseException as exc:  # thread boundary; propagated below
                        capture_error.append(exc)
                        stop_event.set()

                capture_thread = threading.Thread(target=capture, daemon=True, name="orion-qwen-capture")
                capture_thread.start()

                while not stop_event.is_set():
                    if capture_error:
                        raise RuntimeError(f"Microphone streaming failed: {capture_error[0]}") from capture_error[0]
                    try:
                        event = provider._receive_json(ws)
                    except websocket.WebSocketTimeoutException:
                        continue
                    event_type = str(event.get("type") or "")
                    if event_type == "error":
                        raise RuntimeError(provider._error_message(event))
                    if event_type == "response.audio.delta":
                        delta = event.get("delta")
                        if isinstance(delta, str) and delta:
                            if gate.phase is not QwenAudioPhase.SPEAKING:
                                gate.begin_playback()
                                self._set(phase=QwenAudioPhase.SPEAKING, message="Qwen speaking; microphone upload paused automatically")
                            pcm = base64.b64decode(delta)
                            speaker.write(_resample_pcm16_mono(pcm, QWEN_OUTPUT_RATE, audio.output_rate))
                            with self._lock:
                                self._status.output_chunks += 1
                        continue
                    if event_type in {"response.audio.done", "response.done"}:
                        if gate.phase is QwenAudioPhase.SPEAKING:
                            gate.end_playback()
                            self._set(phase=QwenAudioPhase.LISTENING, message="Qwen finished; microphone listening resumed automatically")
                        continue
                    if event_type in {"response.audio_transcript.delta", "conversation.item.input_audio_transcription.delta"}:
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            with self._lock:
                                self._status.transcript = (self._status.transcript + delta)[-4000:]

        except Exception as exc:
            self._set(state=QwenLiveState.ERROR, phase=QwenAudioPhase.IDLE, message=f"{type(exc).__name__}: {exc}")
        finally:
            stop_event.set()
            if capture_thread is not None and capture_thread.is_alive():
                capture_thread.join(timeout=1.0)
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
