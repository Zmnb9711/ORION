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
from orion.qwen_live_diagnostics import QwenLiveDiagnostics
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
    input_native_rate: int
    output_native_rate: int
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
            "instructions": "You are ORION's realtime conversational voice. Talk naturally in the language used by the user.",
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
        return _ResolvedAudio(
            state.resolved_input,
            state.resolved_output,
            input_index,
            output_index,
            input_rate,
            output_rate,
            native_rate,
        )

    def _run(self, request: QwenLiveStartRequest, stop_event: threading.Event) -> None:
        ws = None
        session_update = _audio_session_update(request.model, request.voice)
        turn_detection = session_update["session"]["turn_detection"]
        diagnostics = QwenLiveDiagnostics(
            model=request.model,
            region=request.region,
            vad_type=str(turn_detection["type"]),
            silence_duration_ms=int(turn_detection["silence_duration_ms"]),
            qwen_input_rate=QWEN_INPUT_RATE,
            qwen_output_rate=QWEN_OUTPUT_RATE,
        )
        try:
            import sounddevice as sd
            import websocket

            resolve_start_ns = time.perf_counter_ns()
            audio = self._resolve_audio(sd)
            resolve_end_ns = time.perf_counter_ns()
            diagnostics.record(
                "audio_resolved",
                t_ns=resolve_end_ns,
                resolve_start_ns=resolve_start_ns,
                resolve_end_ns=resolve_end_ns,
                resolve_duration_ms=(resolve_end_ns - resolve_start_ns) / 1_000_000,
            )
            self._set(message="Opening Qwen realtime session", input_name=audio.input_endpoint.name,
                      output_name=audio.output_endpoint.name, input_native_rate=audio.native_rate,
                      output_native_rate=audio.native_rate)
            config = QwenRealtimeConfig(api_key=request.api_key, workspace_id=request.workspace_id,
                                        region=request.region, model=request.model, timeout_s=15.0)
            provider = QwenRealtimeProvider(config)
            connect_start_ns = time.perf_counter_ns()
            ws = provider._connect()
            connect_end_ns = time.perf_counter_ns()
            diagnostics.record(
                "ws_connected",
                t_ns=connect_end_ns,
                connect_start_ns=connect_start_ns,
                connect_end_ns=connect_end_ns,
                connect_duration_ms=(connect_end_ns - connect_start_ns) / 1_000_000,
            )
            ws.settimeout(0.25)
            diagnostics.record("ws_timeout_configured", timeout_ms=250)
            session_send_start_ns = time.perf_counter_ns()
            ws.send(json.dumps(session_update, ensure_ascii=False))
            session_send_end_ns = time.perf_counter_ns()
            diagnostics.record(
                "session_update_sent",
                t_ns=session_send_end_ns,
                send_start_ns=session_send_start_ns,
                send_end_ns=session_send_end_ns,
                send_duration_ms=(session_send_end_ns - session_send_start_ns) / 1_000_000,
            )
            deadline = time.monotonic() + config.timeout_s
            while time.monotonic() < deadline and not stop_event.is_set():
                recv_start_ns = time.perf_counter_ns()
                try:
                    event = provider._receive_json(ws)
                except websocket.WebSocketTimeoutException:
                    recv_end_ns = time.perf_counter_ns()
                    diagnostics.record_recv(
                        recv_start_ns=recv_start_ns,
                        recv_end_ns=recv_end_ns,
                        timeout=True,
                    )
                    continue
                recv_end_ns = time.perf_counter_ns()
                event_type = str(event.get("type") or "")
                diagnostics.record_recv(
                    recv_start_ns=recv_start_ns,
                    recv_end_ns=recv_end_ns,
                    timeout=False,
                    event_type=event_type,
                )
                if event_type == "error":
                    raise RuntimeError(provider._error_message(event))
                if event_type == "session.updated":
                    break
            else:
                raise TimeoutError("Timed out waiting for Qwen session.updated")

            frames = max(1, round(audio.native_rate * CAPTURE_MS / 1000))
            diagnostics.update_audio_metadata(
                input_device=audio.input_endpoint.name,
                output_device=audio.output_endpoint.name,
                input_native_rate=audio.input_native_rate,
                output_native_rate=audio.output_native_rate,
                duplex_rate=audio.native_rate,
                block_frames=frames,
                block_duration_ms=CAPTURE_MS,
            )
            settings = sd.WasapiSettings(exclusive=False)
            self._set(state=QwenLiveState.CONNECTED, message="Qwen connected; opening one full-duplex WASAPI stream")

            # One PortAudio PaStream owns both endpoints. This removes the previous
            # unsupported two-stream topology that could crash the host process.
            with sd.RawStream(samplerate=audio.native_rate, blocksize=frames,
                              device=(audio.input_index, audio.output_index), channels=(CHANNELS, CHANNELS),
                              dtype=("int16", "int16"), extra_settings=(settings, settings)) as stream:
                self._set(state=QwenLiveState.STREAMING, phase=QwenAudioPhase.LISTENING,
                          message="Qwen live audio streaming through one WASAPI duplex stream")
                playback = bytearray()
                while not stop_event.is_set():
                    loop_start_ns = time.perf_counter_ns()
                    # Keep PortAudio I/O serialized on this one thread. No capture
                    # thread races PortAudio calls or the websocket anymore.
                    read_start_ns = time.perf_counter_ns()
                    raw, _overflowed = stream.read(frames)
                    read_end_ns = time.perf_counter_ns()
                    diagnostics.record_capture(
                        read_start_ns=read_start_ns,
                        read_end_ns=read_end_ns,
                        frames_requested=frames,
                        frames_returned=len(raw) // 2,
                        overflow=bool(_overflowed),
                    )
                    input_resample_start_ns = time.perf_counter_ns()
                    qwen_pcm = _resample_pcm16_mono(bytes(raw), audio.native_rate, QWEN_INPUT_RATE)
                    input_resample_end_ns = time.perf_counter_ns()
                    send_start_ns = time.perf_counter_ns()
                    ws.send(json.dumps({"type": "input_audio_buffer.append",
                                        "audio": base64.b64encode(qwen_pcm).decode("ascii")}))
                    send_end_ns = time.perf_counter_ns()
                    diagnostics.record_send(
                        send_start_ns=send_start_ns,
                        send_end_ns=send_end_ns,
                        pcm_frames=len(qwen_pcm) // 2,
                    )
                    with self._lock:
                        self._status.input_chunks += 1

                    # Drain currently available Qwen events without blocking audio
                    # indefinitely. Audio deltas are queued and emitted on this same stream.
                    recv_start_ns = time.perf_counter_ns()
                    recv_timed_out = False
                    try:
                        event = provider._receive_json(ws)
                    except websocket.WebSocketTimeoutException:
                        recv_end_ns = time.perf_counter_ns()
                        recv_timed_out = True
                        diagnostics.record_recv(
                            recv_start_ns=recv_start_ns,
                            recv_end_ns=recv_end_ns,
                            timeout=True,
                        )
                        event = {}
                    else:
                        recv_end_ns = time.perf_counter_ns()
                    event_type = str(event.get("type") or "")
                    if not recv_timed_out:
                        diagnostics.record_recv(
                            recv_start_ns=recv_start_ns,
                            recv_end_ns=recv_end_ns,
                            timeout=False,
                            event_type=event_type,
                        )
                    response_start_ns = time.perf_counter_ns()
                    if event_type == "error":
                        raise RuntimeError(provider._error_message(event))
                    if event_type == "response.audio.delta" and isinstance(event.get("delta"), str):
                        encoded_delta = event["delta"]
                        decoded_delta = base64.b64decode(encoded_delta)
                        response_resample_start_ns = time.perf_counter_ns()
                        resampled_delta = _resample_pcm16_mono(
                            decoded_delta, QWEN_OUTPUT_RATE, audio.native_rate
                        )
                        response_resample_end_ns = time.perf_counter_ns()
                        playback_before_bytes = len(playback)
                        diagnostics.record_audio_delta(
                            receive_ns=recv_end_ns,
                            encoded_chars=len(encoded_delta),
                            decoded_bytes=len(decoded_delta),
                            source_rate=QWEN_OUTPUT_RATE,
                            resample_start_ns=response_resample_start_ns,
                            resample_end_ns=response_resample_end_ns,
                            resampled_bytes=len(resampled_delta),
                            target_rate=audio.native_rate,
                        )
                        playback.extend(resampled_delta)
                        diagnostics.record_playback_enqueue(
                            t_ns=response_resample_end_ns,
                            before_bytes=playback_before_bytes,
                            after_bytes=len(playback),
                            sample_rate=audio.native_rate,
                        )
                        self._set(phase=QwenAudioPhase.SPEAKING, message="Qwen speaking")
                    elif event_type in {"response.audio.done", "response.done"}:
                        self._set(phase=QwenAudioPhase.LISTENING, message="Qwen listening")
                    elif event_type in {"response.audio_transcript.delta", "conversation.item.input_audio_transcription.delta"}:
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            with self._lock:
                                self._status.transcript = (self._status.transcript + delta)[-4000:]
                    response_end_ns = time.perf_counter_ns()

                    bytes_needed = frames * 2
                    playback_before_write_bytes = len(playback)
                    if playback:
                        chunk = bytes(playback[:bytes_needed])
                        del playback[:bytes_needed]
                        response_audio_frames = len(chunk) // 2
                        zero_frames = (bytes_needed - len(chunk)) // 2
                        if len(chunk) < bytes_needed:
                            chunk += b"\x00" * (bytes_needed - len(chunk))
                        with self._lock:
                            self._status.output_chunks += 1
                    else:
                        chunk = b"\x00" * bytes_needed
                        response_audio_frames = 0
                        zero_frames = frames
                    playback_after_write_bytes = len(playback)
                    response_active = diagnostics.response_active or playback_before_write_bytes > 0
                    write_start_ns = time.perf_counter_ns()
                    _underflowed = stream.write(chunk)
                    write_end_ns = time.perf_counter_ns()
                    diagnostics.record_write(
                        write_start_ns=write_start_ns,
                        write_end_ns=write_end_ns,
                        buffer_before_bytes=playback_before_write_bytes,
                        buffer_after_bytes=playback_after_write_bytes,
                        response_audio_frames=response_audio_frames,
                        zero_frames=zero_frames,
                        frames_written=frames,
                        sample_rate=audio.native_rate,
                        underflow=bool(_underflowed),
                        response_active=response_active,
                        preceding_recv_timeout=recv_timed_out,
                        preceding_recv_wait_ms=(recv_end_ns - recv_start_ns)
                        / 1_000_000,
                    )
                    loop_end_ns = time.perf_counter_ns()
                    diagnostics.record_loop(
                        loop_start_ns=loop_start_ns,
                        loop_end_ns=loop_end_ns,
                        read_ms=(read_end_ns - read_start_ns) / 1_000_000,
                        input_resample_ms=(input_resample_end_ns - input_resample_start_ns)
                        / 1_000_000,
                        send_ms=(send_end_ns - send_start_ns) / 1_000_000,
                        recv_ms=(recv_end_ns - recv_start_ns) / 1_000_000,
                        response_processing_ms=(response_end_ns - response_start_ns)
                        / 1_000_000,
                        write_ms=(write_end_ns - write_start_ns) / 1_000_000,
                    )

        except Exception as exc:
            diagnostics.record("session_error", error_type=type(exc).__name__)
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
            try:
                diagnostics.finish()
            except Exception:
                pass


qwen_live_audio = QwenLiveAudioService()
