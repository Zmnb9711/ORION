from __future__ import annotations

import base64
import json
import queue
import threading
import time
from array import array
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from orion.audio_device_config import audio_device_config
from orion.flight_context import FlightContextUpdateGate
from orion.portaudio_devices import (
    PortAudioEndpoint,
    enumerate_portaudio_endpoints,
    portaudio_extra_settings,
    resolve_portaudio_endpoint,
)
from orion.qwen_audio_device import (
    AudioDeviceRateError,
    AudioDeviceRatePlan,
    negotiate_audio_device_rate,
)
from orion.qwen_live_diagnostics import QwenLiveDiagnostics
from orion.qwen_realtime_provider import QwenRealtimeConfig, QwenRealtimeProvider
from orion.realtime_tools import RealtimeToolCall, qwen_live_tool_definition, realtime_tools
from orion.windows_wasapi_backend import WasapiDirection

QWEN_INPUT_RATE = 16_000
QWEN_OUTPUT_RATE = 24_000
CHANNELS = 1
CAPTURE_MS = 40
CAPTURE_QUEUE_BLOCKS = 25
WORKER_JOIN_TIMEOUT_S = 1.0
ENABLE_QWEN_HEARTBEAT = False
ENABLE_QWEN_RESPONSE_WATCHDOG = False
PING_INTERVAL_SEC = 15.0
PONG_TIMEOUT_SEC = 10.0
FIRST_AUDIO_TIMEOUT_SEC = 20.0
INTER_DELTA_TIMEOUT_SEC = 5.0
RESPONSE_COMPLETION_TIMEOUT_SEC = 30.0
QWEN_INSTRUCTIONS = (
    "You are ORION's realtime conversational voice. Talk naturally in the language used by the user. "
    "For ordinary conversation, answer without tools. For a DCS Virtual ATC request, call "
    "orion_virtual_atc_request. ORION Core is authoritative for mission and ATC facts: never invent "
    "an aircraft, airport, runway, clearance, traffic, frequency, telemetry value, or active mission. "
    "If the tool reports unavailable, explain naturally that active DCS mission/ATC context is unavailable."
)


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
    api_key: str = Field(min_length=1, repr=False)
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
    input_endpoint: PortAudioEndpoint
    output_endpoint: PortAudioEndpoint
    input_index: int
    output_index: int
    input_native_rate: int
    output_native_rate: int
    input_rate_plan: AudioDeviceRatePlan | None = None
    output_rate_plan: AudioDeviceRatePlan | None = None
    input_extra_settings: object | None = None
    output_extra_settings: object | None = None


@dataclass(slots=True, frozen=True)
class _WorkerFailure:
    stage: str
    error: Exception


class _HeartbeatTimeoutError(TimeoutError):
    pass


class _ProviderErrorEvent(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class _ResponseTimeout:
    event: str
    response_id: str
    elapsed_ms: float


class _SessionMonitor:
    """Thread-safe monotonic heartbeat and response lifecycle state."""

    def __init__(self, *, connected_ns: int) -> None:
        self._lock = threading.Lock()
        self._connected_ns = connected_ns
        self.last_rx_ns = connected_ns
        self.last_tx_ns = connected_ns
        self.last_ping_ns: int | None = None
        self.last_pong_ns: int | None = None
        self._pong_deadline_ns: int | None = None
        self._response_id = ""
        self._response_created_ns: int | None = None
        self._first_audio_ns: int | None = None
        self._last_delta_ns: int | None = None
        self._ignore_audio_until_created = False

    def record_rx(self, t_ns: int) -> None:
        with self._lock:
            self.last_rx_ns = t_ns

    def record_tx(self, t_ns: int) -> None:
        with self._lock:
            self.last_tx_ns = t_ns

    def ping_due(self, now_ns: int) -> bool:
        with self._lock:
            reference = self.last_ping_ns or self._connected_ns
            return (
                self._pong_deadline_ns is None
                and now_ns - reference >= int(PING_INTERVAL_SEC * 1_000_000_000)
            )

    def record_ping(self, t_ns: int) -> None:
        with self._lock:
            self.last_ping_ns = t_ns
            self.last_tx_ns = t_ns
            self._pong_deadline_ns = t_ns + int(PONG_TIMEOUT_SEC * 1_000_000_000)

    def record_pong(self, t_ns: int) -> None:
        with self._lock:
            self.last_rx_ns = t_ns
            self.last_pong_ns = t_ns
            self._pong_deadline_ns = None

    def heartbeat_expired(self, now_ns: int) -> bool:
        with self._lock:
            return (
                self._pong_deadline_ns is not None
                and now_ns >= self._pong_deadline_ns
            )

    def ages_ms(self, now_ns: int) -> dict[str, float | None]:
        with self._lock:
            return {
                "last_rx_age_ms": (now_ns - self.last_rx_ns) / 1_000_000,
                "last_tx_age_ms": (now_ns - self.last_tx_ns) / 1_000_000,
                "last_ping_age_ms": (
                    (now_ns - self.last_ping_ns) / 1_000_000
                    if self.last_ping_ns is not None
                    else None
                ),
                "last_pong_age_ms": (
                    (now_ns - self.last_pong_ns) / 1_000_000
                    if self.last_pong_ns is not None
                    else None
                ),
            }

    def response_created(self, event: dict[str, Any], t_ns: int) -> None:
        response = event.get("response")
        response_id = response.get("id") if isinstance(response, dict) else None
        with self._lock:
            self._response_id = str(response_id or event.get("response_id") or "")
            self._response_created_ns = t_ns
            self._first_audio_ns = None
            self._last_delta_ns = None
            self._ignore_audio_until_created = False

    def audio_delta(self, t_ns: int) -> bool:
        with self._lock:
            if self._ignore_audio_until_created:
                return False
            if self._response_created_ns is None:
                self._response_created_ns = t_ns
            if self._first_audio_ns is None:
                self._first_audio_ns = t_ns
            self._last_delta_ns = t_ns
            return True

    def response_audio_done(self, t_ns: int) -> None:
        with self._lock:
            if self._response_created_ns is None:
                return
            if self._first_audio_ns is None:
                self._first_audio_ns = t_ns
            self._last_delta_ns = None

    def response_done(self) -> None:
        with self._lock:
            self._clear_response_locked()

    def response_timeout(self, now_ns: int) -> _ResponseTimeout | None:
        with self._lock:
            created_ns = self._response_created_ns
            if created_ns is None:
                return None
            event = ""
            start_ns = created_ns
            if now_ns - created_ns >= int(
                RESPONSE_COMPLETION_TIMEOUT_SEC * 1_000_000_000
            ):
                event = "RESPONSE_COMPLETION_TIMEOUT"
            elif self._first_audio_ns is None and now_ns - created_ns >= int(
                FIRST_AUDIO_TIMEOUT_SEC * 1_000_000_000
            ):
                event = "RESPONSE_FIRST_AUDIO_TIMEOUT"
            elif self._last_delta_ns is not None and now_ns - self._last_delta_ns >= int(
                INTER_DELTA_TIMEOUT_SEC * 1_000_000_000
            ):
                event = "RESPONSE_INTER_DELTA_TIMEOUT"
                start_ns = self._last_delta_ns
            if not event:
                return None
            timeout = _ResponseTimeout(
                event=event,
                response_id=self._response_id,
                elapsed_ms=(now_ns - start_ns) / 1_000_000,
            )
            self._clear_response_locked()
            self._ignore_audio_until_created = True
            return timeout

    def _clear_response_locked(self) -> None:
        self._response_id = ""
        self._response_created_ns = None
        self._first_audio_ns = None
        self._last_delta_ns = None


class _PlaybackFifo:
    """Unbounded provider-delta FIFO matching the working reference client."""

    def __init__(self) -> None:
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._lock = threading.Lock()
        self._depth_bytes = 0
        self._response_active = False

    @property
    def depth_bytes(self) -> int:
        with self._lock:
            return self._depth_bytes

    def mark_response_active(self, active: bool) -> None:
        with self._lock:
            self._response_active = active

    def put(self, pcm: bytes) -> tuple[int, int]:
        if not pcm or len(pcm) % 2:
            raise ValueError("Playback PCM must contain complete int16 samples")
        with self._lock:
            before = self._depth_bytes
            self._depth_bytes += len(pcm)
            self._queue.put_nowait(pcm)
            return before, self._depth_bytes

    def get(self) -> tuple[bytes | None, int, int, bool]:
        pcm = self._queue.get()
        with self._lock:
            before = self._depth_bytes
            if pcm is not None:
                self._depth_bytes -= len(pcm)
            return pcm, before, self._depth_bytes, self._response_active

    def stop(self) -> None:
        self._queue.put_nowait(None)


def _put_drop_oldest(
    target: queue.Queue[bytes], item: bytes
) -> tuple[int, int]:
    """Put without blocking, dropping the oldest queued capture block if full."""

    dropped_bytes = 0
    while True:
        try:
            target.put_nowait(item)
            return target.qsize(), dropped_bytes
        except queue.Full:
            try:
                dropped_bytes += len(target.get_nowait())
            except queue.Empty:
                continue


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


def _pcm16_mono_levels(data: bytes) -> tuple[float, float]:
    """Return normalized RMS and peak without retaining captured PCM."""

    samples = array("h")
    samples.frombytes(data)
    if not samples:
        return 0.0, 0.0
    peak = max(abs(sample) for sample in samples) / 32768.0
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    return (mean_square**0.5) / 32768.0, peak


def _install_websocket_frame_telemetry(
    ws: Any,
    websocket: Any,
    diagnostics: QwenLiveDiagnostics,
    monitor: _SessionMonitor | None = None,
) -> None:
    """Observe control frames without changing websocket-client receive behavior."""

    recv_frame = getattr(ws, "recv_frame", None)
    abnf = getattr(websocket, "ABNF", None)
    if not callable(recv_frame) or abnf is None:
        diagnostics.record_websocket_event(
            "CONTROL_FRAME_TELEMETRY_UNAVAILABLE",
            direction="lifecycle",
        )
        return
    if getattr(ws, "_orion_forensic_telemetry_installed", False):
        return

    def monitored_recv_frame(*args: object, **kwargs: object) -> Any:
        frame = recv_frame(*args, **kwargs)
        opcode = getattr(frame, "opcode", None)
        frame_data = getattr(frame, "data", b"")
        now_ns = time.perf_counter_ns()
        if monitor is not None:
            monitor.record_rx(now_ns)
        if opcode == abnf.OPCODE_CLOSE:
            if isinstance(frame_data, str):
                close_data = frame_data.encode("utf-8", errors="replace")
            else:
                close_data = bytes(frame_data)
            diagnostics.record_websocket_close_frame(close_data, t_ns=now_ns)
        elif opcode == abnf.OPCODE_PING:
            diagnostics.record_websocket_event(
                "PING_RECEIVED",
                direction="recv",
                operation="recv",
                t_ns=now_ns,
            )
        elif opcode == abnf.OPCODE_PONG:
            if monitor is not None:
                monitor.record_pong(now_ns)
            ages = monitor.ages_ms(now_ns) if monitor is not None else {}
            diagnostics.record_websocket_event(
                "PONG_RECEIVED",
                direction="recv",
                operation="recv",
                t_ns=now_ns,
                last_rx_age_ms=ages.get("last_rx_age_ms"),
                last_tx_age_ms=ages.get("last_tx_age_ms"),
                last_ping_age_ms=ages.get("last_ping_age_ms"),
                last_pong_age_ms=ages.get("last_pong_age_ms"),
            )
        return frame

    try:
        setattr(ws, "recv_frame", monitored_recv_frame)
        setattr(ws, "_orion_forensic_telemetry_installed", True)
    except (AttributeError, TypeError):
        diagnostics.record_websocket_event(
            "CONTROL_FRAME_TELEMETRY_UNAVAILABLE",
            direction="lifecycle",
        )
        return

    ping = getattr(ws, "ping", None)
    if callable(ping):

        def monitored_ping(*args: object, **kwargs: object) -> Any:
            now_ns = time.perf_counter_ns()
            ages = monitor.ages_ms(now_ns) if monitor is not None else {}
            diagnostics.record_websocket_event(
                "PING_SENT",
                direction="send",
                operation="control_send",
                t_ns=now_ns,
                last_rx_age_ms=ages.get("last_rx_age_ms"),
                last_tx_age_ms=ages.get("last_tx_age_ms"),
                last_ping_age_ms=ages.get("last_ping_age_ms"),
                last_pong_age_ms=ages.get("last_pong_age_ms"),
            )
            return ping(*args, **kwargs)

        setattr(ws, "ping", monitored_ping)

    pong = getattr(ws, "pong", None)
    if callable(pong):

        def monitored_pong(*args: object, **kwargs: object) -> Any:
            diagnostics.record_websocket_event(
                "PONG_SENT", direction="send", operation="control_send"
            )
            return pong(*args, **kwargs)

        setattr(ws, "pong", monitored_pong)


def _audio_session_update(
    model: str,
    voice: str,
    *,
    instructions: str = QWEN_INSTRUCTIONS,
) -> dict[str, Any]:
    normalized = model.strip().casefold()
    vad_type = "semantic_vad" if normalized == "qwen3.5-omni-realtime" or normalized.startswith("qwen3.5-omni-realtime-") else "server_vad"
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "voice": voice,
            "instructions": instructions,
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            # Provider-side ASR is observational: it exposes what Qwen heard
            # without changing VAD, response triggering, or audio transport.
            "input_audio_transcription": {
                "model": "qwen3-asr-flash-realtime"
            },
            "turn_detection": {"type": vad_type, "threshold": 0.5, "silence_duration_ms": 800},
            "tools": [qwen_live_tool_definition()],
        },
    }


class QwenLiveAudioService:
    """Qwen realtime speech-to-speech with independent blocking audio streams."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = QwenLiveStatus()
        self._active_diagnostics: QwenLiveDiagnostics | None = None

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
        with self._lock:
            diagnostics = self._active_diagnostics
        if diagnostics is not None:
            diagnostics.record_websocket_event(
                "STOP_REQUESTED",
                direction="lifecycle",
                stop_source="service.stop",
            )
            diagnostics.record_websocket_event(
                "CONNECTION_CLASSIFIED",
                direction="lifecycle",
                classification="MANUAL_STOP",
            )
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        with self._lock:
            self._status = QwenLiveStatus(message="Qwen live audio stopped")
            return self._status.model_copy(deep=True)

    def _set(self, **changes: Any) -> None:
        with self._lock:
            payload = self._status.model_dump()
            payload.update(changes)
            self._status = QwenLiveStatus.model_validate(payload)

    def _resolve_audio(self, sd: Any) -> _ResolvedAudio:
        state = audio_device_config.state()
        if state.resolved_input is None or state.resolved_output is None:
            raise RuntimeError(state.message or "ORION Core audio input/output selection is not ready")
        runtime_endpoints = enumerate_portaudio_endpoints(sd)
        input_endpoint = resolve_portaudio_endpoint(
            runtime_endpoints,
            state.selection.input_device_id,
            WasapiDirection.INPUT,
            identity=state.selection.input_identity,
        )
        output_endpoint = resolve_portaudio_endpoint(
            runtime_endpoints,
            state.selection.output_device_id,
            WasapiDirection.OUTPUT,
            identity=state.selection.output_identity,
        )
        input_settings, input_settings_mode = portaudio_extra_settings(
            sd, input_endpoint
        )
        output_settings, output_settings_mode = portaudio_extra_settings(
            sd, output_endpoint
        )
        input_plan = negotiate_audio_device_rate(
            sd,
            direction="input",
            logical_device_id=state.selection.input_device_id,
            persisted_identity=input_endpoint.identity().model_dump_json(),
            device_index=input_endpoint.device_index,
            protocol_rate=QWEN_INPUT_RATE,
            extra_settings=input_settings,
            extra_settings_mode=input_settings_mode,
        )
        output_plan = negotiate_audio_device_rate(
            sd,
            direction="output",
            logical_device_id=state.selection.output_device_id,
            persisted_identity=output_endpoint.identity().model_dump_json(),
            device_index=output_endpoint.device_index,
            protocol_rate=QWEN_OUTPUT_RATE,
            extra_settings=output_settings,
            extra_settings_mode=output_settings_mode,
        )
        return _ResolvedAudio(
            input_endpoint,
            output_endpoint,
            input_endpoint.device_index,
            output_endpoint.device_index,
            input_plan.physical_rate,
            output_plan.physical_rate,
            input_plan,
            output_plan,
            input_settings,
            output_settings,
        )

    @staticmethod
    def _record_audio_rate_plan(
        diagnostics: QwenLiveDiagnostics,
        plan: AudioDeviceRatePlan,
    ) -> None:
        for rejection in plan.rejected_rates:
            diagnostics.record(
                "audio_rate_candidate_rejected",
                direction=plan.direction.upper(),
                logical_device_id=plan.logical_device_id,
                device_index=plan.device_index,
                device_name=plan.device_name,
                candidate_rate=rejection.rate,
                error_type=rejection.error_type,
                error=rejection.message,
            )
        diagnostics.record(
            "audio_device_rate_selected",
            direction=plan.direction.upper(),
            logical_device_id=plan.logical_device_id,
            selected_persistent_endpoint_id=plan.logical_device_id,
            persisted_identity=plan.persisted_identity,
            device_index=plan.device_index,
            device_name=plan.device_name,
            host_api_index=plan.host_api_index,
            host_api=plan.host_api,
            max_input_channels=plan.max_input_channels,
            max_output_channels=plan.max_output_channels,
            reported_default_samplerate=plan.default_rate,
            attempted_rates=",".join(str(rate) for rate in plan.attempted_rates),
            selected_native_rate=plan.physical_rate,
            protocol_rate=plan.protocol_rate,
            path=plan.path.upper(),
            resampling_required=plan.resampling_required,
            stream_class=(
                "RawInputStream" if plan.direction == "input" else "RawOutputStream"
            ),
            extra_settings_mode=plan.extra_settings_mode,
            extra_settings_type=plan.extra_settings_type,
        )

    @staticmethod
    def _record_audio_rate_error(
        diagnostics: QwenLiveDiagnostics,
        error: AudioDeviceRateError,
    ) -> None:
        for rejection in error.rejected_rates:
            diagnostics.record(
                "audio_rate_candidate_rejected",
                direction=error.direction.upper(),
                logical_device_id=error.logical_device_id,
                device_index=error.device_index,
                device_name=error.device_name,
                candidate_rate=rejection.rate,
                error_type=rejection.error_type,
                error=rejection.message,
            )
        diagnostics.record(
            "audio_device_rate_unavailable",
            direction=error.direction.upper(),
            logical_device_id=error.logical_device_id,
            device_index=error.device_index,
            device_name=error.device_name,
            reported_default_samplerate=error.default_rate,
            attempted_rates=",".join(str(rate) for rate in error.attempted_rates),
        )

    @staticmethod
    def _audio_stream_open_error(
        *,
        direction: str,
        endpoint: PortAudioEndpoint,
        device_index: int,
        native_rate: int,
        plan: AudioDeviceRatePlan | None,
        error: Exception,
    ) -> RuntimeError:
        default_rate = plan.default_rate if plan is not None else None
        attempted_rates = (
            plan.attempted_rates if plan is not None else (native_rate,)
        )
        logical_device_id = (
            plan.logical_device_id if plan is not None else endpoint.device_id
        )
        return RuntimeError(
            f"Selected {direction} audio endpoint failed to open: "
            f"{endpoint.name} [index={device_index}, id={logical_device_id}]; "
            f"reported default={default_rate}; attempted rates={attempted_rates}; "
            f"selected rate={native_rate}; underlying error="
            f"{type(error).__name__}: {error}"
        )

    @staticmethod
    def _report_worker_failure(
        failures: queue.Queue[_WorkerFailure],
        stop_event: threading.Event,
        diagnostics: QwenLiveDiagnostics,
        stage: str,
        error: Exception,
    ) -> None:
        diagnostics.record_websocket_event(
            "WORKER_FAILURE_REPORTED",
            direction="lifecycle",
            stage=stage,
            exception_type=type(error).__name__,
            stop_event_before=stop_event.is_set(),
        )
        try:
            failures.put_nowait(_WorkerFailure(stage, error))
        except queue.Full:
            pass
        stop_event.set()
        diagnostics.record_websocket_event(
            "STOP_EVENT_SET",
            direction="lifecycle",
            stage=stage,
            stop_event_after=stop_event.is_set(),
        )

    @staticmethod
    def _record_turn_event_safely(
        diagnostics: QwenLiveDiagnostics,
        event: dict[str, Any],
        *,
        t_ns: int,
    ) -> None:
        try:
            diagnostics.record_turn_event(event, t_ns=t_ns)
        except Exception as exc:
            try:
                diagnostics.record_turn_forensics_failure(t_ns=t_ns, error=exc)
            except Exception:
                pass

    @staticmethod
    def _record_playback_write_start_safely(
        diagnostics: QwenLiveDiagnostics,
        *,
        t_ns: int,
        buffer_after_bytes: int,
        response_audio_bytes: int,
        sample_rate: int,
        pcm: bytes | None = None,
    ) -> None:
        try:
            diagnostics.record_playback_write_start(
                t_ns=t_ns,
                buffer_after_bytes=buffer_after_bytes,
                response_audio_bytes=response_audio_bytes,
                sample_rate=sample_rate,
                pcm=pcm,
            )
        except Exception as exc:
            try:
                diagnostics.record_turn_forensics_failure(t_ns=t_ns, error=exc)
            except Exception:
                pass

    @staticmethod
    def _record_microphone_analysis_pcm_safely(
        diagnostics: QwenLiveDiagnostics,
        *,
        pcm: bytes,
        sample_rate: int,
        end_ns: int,
    ) -> None:
        try:
            diagnostics.record_microphone_analysis_pcm(
                pcm=pcm,
                sample_rate=sample_rate,
                end_ns=end_ns,
            )
        except Exception as exc:
            try:
                diagnostics.record_turn_forensics_failure(
                    t_ns=end_ns,
                    error=exc,
                )
            except Exception:
                pass

    def _send_worker(
        self,
        ws: Any,
        stop_event: threading.Event,
        capture_queue: queue.Queue[bytes],
        diagnostics: QwenLiveDiagnostics,
        failures: queue.Queue[_WorkerFailure],
        send_lock: threading.Lock,
        monitor: _SessionMonitor,
        flight_context_gate: FlightContextUpdateGate | None = None,
        model: str = "qwen3.5-omni-flash-realtime",
        voice: str = "Tina",
    ) -> None:
        diagnostics.record("worker_started", stage="websocket_send")
        try:
            while not stop_event.is_set():
                if flight_context_gate is not None:
                    update = flight_context_gate.next_update()
                    if update is not None:
                        with send_lock:
                            ws.send(
                                json.dumps(
                                    _audio_session_update(
                                        model,
                                        voice,
                                        instructions=update.instructions,
                                    ),
                                    ensure_ascii=False,
                                )
                            )
                        count = flight_context_gate.mark_applied(update)
                        monitor.record_tx(time.perf_counter_ns())
                        diagnostics.record(
                            "flight_context_applied",
                            context_state=update.state.value,
                            context_fresh=update.fresh,
                            aircraft_type=update.aircraft_type,
                            context_generation=update.generation,
                            context_update_count=count,
                            provider="qwen",
                        )
                try:
                    qwen_pcm = capture_queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                send_start_ns = time.perf_counter_ns()
                diagnostics.record_websocket_event(
                    "AUDIO_SEND_START",
                    direction="send",
                    operation="send",
                    t_ns=send_start_ns,
                    event_type="input_audio_buffer.append",
                )
                with send_lock:
                    ws.send(
                        json.dumps(
                            {
                                "type": "input_audio_buffer.append",
                                "audio": base64.b64encode(qwen_pcm).decode("ascii"),
                            }
                        )
                    )
                send_end_ns = time.perf_counter_ns()
                monitor.record_tx(send_end_ns)
                diagnostics.record_websocket_event(
                    "AUDIO_SEND_END",
                    direction="send",
                    operation="send",
                    t_ns=send_end_ns,
                    event_type="input_audio_buffer.append",
                )
                diagnostics.record_send(
                    send_start_ns=send_start_ns,
                    send_end_ns=send_end_ns,
                    pcm_frames=len(qwen_pcm) // 2,
                )
        except Exception as exc:
            diagnostics.record_websocket_event(
                "CONNECTION_CLASSIFIED",
                direction="lifecycle",
                classification="SEND_FAILURE",
                exception_type=type(exc).__name__,
            )
            diagnostics.record_websocket_exception(
                exc,
                ws=ws,
                stage="send",
                fatal=not stop_event.is_set(),
            )
            if not stop_event.is_set():
                self._report_worker_failure(
                    failures,
                    stop_event,
                    diagnostics,
                    "websocket send",
                    exc,
                )
        finally:
            diagnostics.record_websocket_event(
                "WORKER_EXIT",
                direction="lifecycle",
                worker="websocket_send",
                stop_event=stop_event.is_set(),
            )
            diagnostics.record("worker_stopped", stage="websocket_send")

    def _playback_worker(
        self,
        sd: Any,
        audio: _ResolvedAudio,
        stop_event: threading.Event,
        playback: _PlaybackFifo,
        diagnostics: QwenLiveDiagnostics,
        failures: queue.Queue[_WorkerFailure],
    ) -> None:
        diagnostics.record("worker_started", stage="audio_playback")
        try:
            try:
                output_stream = sd.RawOutputStream(
                    samplerate=audio.output_native_rate,
                    device=audio.output_index,
                    channels=CHANNELS,
                    dtype="int16",
                    extra_settings=getattr(audio, "output_extra_settings", None),
                )
            except Exception as exc:
                raise self._audio_stream_open_error(
                    direction="OUTPUT",
                    endpoint=audio.output_endpoint,
                    device_index=audio.output_index,
                    native_rate=audio.output_native_rate,
                    plan=audio.output_rate_plan,
                    error=exc,
                ) from exc
            with output_stream as stream:
                while True:
                    wait_start_ns = time.perf_counter_ns()
                    diagnostics.record_playback_wait_start(
                        t_ns=wait_start_ns,
                        depth_bytes=playback.depth_bytes,
                        sample_rate=audio.output_native_rate,
                    )
                    pcm, before_bytes, after_bytes, response_active = playback.get()
                    wait_end_ns = time.perf_counter_ns()
                    diagnostics.record_playback_wait_end(
                        t_ns=wait_end_ns,
                        depth_bytes=after_bytes,
                        sample_rate=audio.output_native_rate,
                    )
                    if pcm is None or stop_event.is_set():
                        return
                    write_start_ns = time.perf_counter_ns()
                    self._record_playback_write_start_safely(
                        diagnostics,
                        t_ns=write_start_ns,
                        buffer_after_bytes=after_bytes,
                        response_audio_bytes=len(pcm),
                        sample_rate=audio.output_native_rate,
                        pcm=pcm,
                    )
                    underflowed = stream.write(pcm)
                    write_end_ns = time.perf_counter_ns()
                    with self._lock:
                        self._status.output_chunks += 1
                    diagnostics.record_write(
                        write_start_ns=write_start_ns,
                        write_end_ns=write_end_ns,
                        buffer_before_bytes=before_bytes,
                        buffer_after_bytes=after_bytes,
                        response_audio_frames=len(pcm) // 2,
                        zero_frames=0,
                        frames_written=len(pcm) // 2,
                        sample_rate=audio.output_native_rate,
                        underflow=bool(underflowed),
                        response_active=response_active,
                    )
        except Exception as exc:
            if not stop_event.is_set():
                self._report_worker_failure(
                    failures,
                    stop_event,
                    diagnostics,
                    "audio playback",
                    exc,
                )
        finally:
            diagnostics.record("worker_stopped", stage="audio_playback")

    def _heartbeat_worker(
        self,
        ws: Any,
        stop_event: threading.Event,
        diagnostics: QwenLiveDiagnostics,
        failures: queue.Queue[_WorkerFailure],
        send_lock: threading.Lock,
        monitor: _SessionMonitor,
    ) -> None:
        diagnostics.record("worker_started", stage="websocket_heartbeat")
        try:
            while not stop_event.wait(0.05):
                now_ns = time.perf_counter_ns()
                if monitor.heartbeat_expired(now_ns):
                    ages = monitor.ages_ms(now_ns)
                    diagnostics.record_websocket_event(
                        "PONG_TIMEOUT",
                        direction="lifecycle",
                        t_ns=now_ns,
                        last_rx_age_ms=ages["last_rx_age_ms"],
                        last_tx_age_ms=ages["last_tx_age_ms"],
                        last_ping_age_ms=ages["last_ping_age_ms"],
                        last_pong_age_ms=ages["last_pong_age_ms"],
                    )
                    diagnostics.record_websocket_event(
                        "CONNECTION_CLASSIFIED",
                        direction="lifecycle",
                        t_ns=now_ns,
                        classification="HEARTBEAT_TIMEOUT",
                    )
                    raise _HeartbeatTimeoutError(
                        f"Qwen WebSocket pong was not received within {PONG_TIMEOUT_SEC:g}s"
                    )
                if not monitor.ping_due(now_ns):
                    continue
                with send_lock:
                    ping_ns = time.perf_counter_ns()
                    monitor.record_ping(ping_ns)
                    ws.ping()
        except Exception as exc:
            diagnostics.record_websocket_exception(
                exc,
                ws=ws,
                stage="heartbeat",
                fatal=not stop_event.is_set(),
            )
            if not stop_event.is_set():
                self._report_worker_failure(
                    failures,
                    stop_event,
                    diagnostics,
                    "websocket heartbeat",
                    exc,
                )
        finally:
            diagnostics.record_websocket_event(
                "WORKER_EXIT",
                direction="lifecycle",
                worker="websocket_heartbeat",
                stop_event=stop_event.is_set(),
            )
            diagnostics.record("worker_stopped", stage="websocket_heartbeat")

    def _apply_response_timeout(
        self,
        *,
        monitor: _SessionMonitor,
        now_ns: int,
        playback: _PlaybackFifo,
        diagnostics: QwenLiveDiagnostics,
    ) -> bool:
        response_timeout = monitor.response_timeout(now_ns)
        if response_timeout is None:
            return False
        playback.mark_response_active(False)
        diagnostics.record_websocket_event(
            response_timeout.event,
            direction="lifecycle",
            t_ns=now_ns,
            response_id=response_timeout.response_id,
            elapsed_ms=response_timeout.elapsed_ms,
        )
        self._set(
            phase=QwenAudioPhase.LISTENING,
            message="Qwen response stalled; listening for a new turn",
        )
        return True

    @staticmethod
    def _handle_realtime_tool_call(
        *,
        ws: Any,
        event: dict[str, Any],
        diagnostics: QwenLiveDiagnostics,
        monitor: _SessionMonitor,
    ) -> None:
        started_ns = time.perf_counter_ns()
        call_id = str(event.get("call_id") or "")
        provider_name = str(event.get("name") or "")
        raw_arguments = event.get("arguments")
        core_name = {
            "orion_virtual_atc_request": "orion.virtual_atc.request",
        }.get(provider_name, provider_name)
        diagnostics.record_websocket_event(
            "CORE_TOOL_REQUEST",
            direction="tool",
            call_id=call_id,
            tool_name=core_name,
        )
        if not call_id or not provider_name:
            raise RuntimeError("Qwen returned an incomplete function call")
        try:
            arguments = json.loads(raw_arguments or "{}") if isinstance(raw_arguments, str) else raw_arguments
        except json.JSONDecodeError:
            arguments = None
        if not isinstance(arguments, dict):
            result = {
                "call_id": call_id,
                "name": core_name,
                "ok": False,
                "output": {},
                "error": "Invalid tool arguments JSON object",
            }
        else:
            result = realtime_tools.execute(
                RealtimeToolCall(call_id=call_id, name=core_name, arguments=arguments)
            ).model_dump(mode="json")
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        output = result.get("output")
        route = output.get("domain") if isinstance(output, dict) else None
        diagnostics.record_websocket_event(
            "CORE_TOOL_RESULT",
            direction="tool",
            call_id=call_id,
            tool_name=core_name,
            accepted=bool(result.get("ok")),
            route=route,
            result_status=output.get("status") if isinstance(output, dict) else None,
            latency_ms=latency_ms,
        )
        ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result, ensure_ascii=False),
                    },
                },
                ensure_ascii=False,
            )
        )
        ws.send(json.dumps({"type": "response.create", "response": {"modalities": ["text", "audio"]}}))
        sent_ns = time.perf_counter_ns()
        monitor.record_tx(sent_ns)
        diagnostics.record_websocket_event(
            "CORE_TOOL_FOLLOWUP_REQUESTED",
            direction="send",
            call_id=call_id,
            tool_name=core_name,
            t_ns=sent_ns,
        )

    def _receive_worker(
        self,
        ws: Any,
        websocket: Any,
        provider: QwenRealtimeProvider,
        audio: _ResolvedAudio,
        stop_event: threading.Event,
        playback: _PlaybackFifo,
        diagnostics: QwenLiveDiagnostics,
        failures: queue.Queue[_WorkerFailure],
        monitor: _SessionMonitor,
    ) -> None:
        diagnostics.record("worker_started", stage="websocket_receive")
        try:
            while not stop_event.is_set():
                recv_start_ns = time.perf_counter_ns()
                diagnostics.record_websocket_event(
                    "RECV_EVENT_START",
                    direction="recv",
                    operation="recv",
                    t_ns=recv_start_ns,
                )
                try:
                    event = provider._receive_json(ws)
                except websocket.WebSocketTimeoutException as exc:
                    recv_end_ns = time.perf_counter_ns()
                    diagnostics.record_websocket_exception(
                        exc,
                        ws=ws,
                        stage="recv",
                        fatal=False,
                        t_ns=recv_end_ns,
                    )
                    diagnostics.record_recv(
                        recv_start_ns=recv_start_ns,
                        recv_end_ns=recv_end_ns,
                        timeout=True,
                    )
                    if ENABLE_QWEN_RESPONSE_WATCHDOG:
                        self._apply_response_timeout(
                            monitor=monitor,
                            now_ns=recv_end_ns,
                            playback=playback,
                            diagnostics=diagnostics,
                        )
                    continue
                recv_end_ns = time.perf_counter_ns()
                monitor.record_rx(recv_end_ns)
                if ENABLE_QWEN_RESPONSE_WATCHDOG:
                    self._apply_response_timeout(
                        monitor=monitor,
                        now_ns=recv_end_ns,
                        playback=playback,
                        diagnostics=diagnostics,
                    )
                event_type = str(event.get("type") or "")
                diagnostics.record_websocket_event(
                    "RECV_EVENT_SUCCESS",
                    direction="recv",
                    operation="recv",
                    t_ns=recv_end_ns,
                    event_type=event_type,
                )
                diagnostics.record_recv(
                    recv_start_ns=recv_start_ns,
                    recv_end_ns=recv_end_ns,
                    timeout=False,
                    event_type=event_type,
                )
                self._record_turn_event_safely(
                    diagnostics,
                    event,
                    t_ns=recv_end_ns,
                )
                processing_start_ns = time.perf_counter_ns()
                if event_type == "error":
                    diagnostics.record_websocket_event(
                        "CONNECTION_CLASSIFIED",
                        direction="lifecycle",
                        classification="PROVIDER_ERROR_EVENT",
                    )
                    raise _ProviderErrorEvent(provider._error_message(event))
                if event_type == "response.created":
                    monitor.response_created(event, recv_end_ns)
                    playback.mark_response_active(True)
                if event_type == "response.function_call_arguments.done":
                    self._handle_realtime_tool_call(
                        ws=ws,
                        event=event,
                        diagnostics=diagnostics,
                        monitor=monitor,
                    )
                if event_type == "response.audio.delta" and isinstance(
                    event.get("delta"), str
                ):
                    encoded_delta = event["delta"]
                    decoded_delta = base64.b64decode(encoded_delta, validate=True)
                    response_resample_start_ns = time.perf_counter_ns()
                    # The reference path writes protocol-native provider PCM
                    # unchanged. Resampling is only a compatibility fallback.
                    resampled_delta = (
                        decoded_delta
                        if audio.output_native_rate == QWEN_OUTPUT_RATE
                        else _resample_pcm16_mono(
                            decoded_delta,
                            QWEN_OUTPUT_RATE,
                            audio.output_native_rate,
                        )
                    )
                    if not monitor.audio_delta(recv_end_ns):
                        diagnostics.record_websocket_event(
                            "LATE_RESPONSE_AUDIO_IGNORED",
                            direction="recv",
                            operation="recv",
                            t_ns=recv_end_ns,
                        )
                        continue
                    response_resample_end_ns = time.perf_counter_ns()
                    diagnostics.record_audio_delta(
                        receive_ns=recv_end_ns,
                        encoded_chars=len(encoded_delta),
                        decoded_bytes=len(decoded_delta),
                        source_rate=QWEN_OUTPUT_RATE,
                        resample_start_ns=response_resample_start_ns,
                        resample_end_ns=response_resample_end_ns,
                        resampled_bytes=len(resampled_delta),
                        target_rate=audio.output_native_rate,
                        response_id=str(event.get("response_id") or ""),
                        item_id=str(event.get("item_id") or ""),
                    )
                    playback.mark_response_active(True)
                    before_bytes, after_bytes = playback.put(resampled_delta)
                    diagnostics.record_playback_enqueue(
                        t_ns=response_resample_end_ns,
                        before_bytes=before_bytes,
                        after_bytes=after_bytes,
                        sample_rate=audio.output_native_rate,
                        added_bytes=len(resampled_delta),
                    )
                    self._set(phase=QwenAudioPhase.SPEAKING, message="Qwen speaking")
                elif event_type == "response.audio.done":
                    monitor.response_audio_done(recv_end_ns)
                    playback.mark_response_active(False)
                    self._set(
                        phase=QwenAudioPhase.LISTENING,
                        message="Qwen listening",
                    )
                elif event_type == "response.done":
                    monitor.response_done()
                    playback.mark_response_active(False)
                    self._set(
                        phase=QwenAudioPhase.LISTENING,
                        message="Qwen listening",
                    )
                elif event_type in {
                    "response.audio_transcript.delta",
                    "conversation.item.input_audio_transcription.delta",
                }:
                    delta = event.get("delta")
                    if isinstance(delta, str):
                        with self._lock:
                            self._status.transcript = (
                                self._status.transcript + delta
                            )[-4000:]
                processing_end_ns = time.perf_counter_ns()
                diagnostics.record_stage_timing(
                    "response_processing",
                    start_ns=processing_start_ns,
                    end_ns=processing_end_ns,
                )
        except Exception as exc:
            if stop_event.is_set():
                diagnostics.record_websocket_event(
                    "LOCAL_SHUTDOWN_RECEIVE_EXIT",
                    direction="lifecycle",
                    exception_type=type(exc).__name__,
                    exception_message=str(exc),
                )
                return
            if diagnostics.websocket_clean_close:
                diagnostics.record_websocket_event(
                    "CLEAN_REMOTE_CLOSE",
                    direction="lifecycle",
                    stop_event_before=stop_event.is_set(),
                )
                stop_event.set()
                return
            classification = (
                "PROVIDER_ERROR_EVENT"
                if isinstance(exc, _ProviderErrorEvent)
                else "ABRUPT_EOF"
                if type(exc).__name__ == "WebSocketConnectionClosedException"
                else "RECEIVE_FAILURE"
            )
            diagnostics.record_websocket_event(
                "CONNECTION_CLASSIFIED",
                direction="lifecycle",
                classification=classification,
                exception_type=type(exc).__name__,
            )
            diagnostics.record_websocket_exception(
                exc,
                ws=ws,
                stage="recv",
                fatal=not stop_event.is_set(),
            )
            if not stop_event.is_set():
                self._report_worker_failure(
                    failures,
                    stop_event,
                    diagnostics,
                    "websocket receive",
                    exc,
                )
        finally:
            diagnostics.record_websocket_event(
                "WORKER_EXIT",
                direction="lifecycle",
                worker="websocket_receive",
                stop_event=stop_event.is_set(),
            )
            diagnostics.record("worker_stopped", stage="websocket_receive")

    def _run_transport(
        self,
        *,
        sd: Any,
        websocket: Any,
        ws: Any,
        provider: QwenRealtimeProvider,
        audio: _ResolvedAudio,
        frames: int,
        stop_event: threading.Event,
        diagnostics: QwenLiveDiagnostics,
        monitor: _SessionMonitor | None = None,
        flight_context_gate: FlightContextUpdateGate | None = None,
        model: str = "qwen3.5-omni-flash-realtime",
        voice: str = "Tina",
    ) -> None:
        if monitor is None:
            monitor = _SessionMonitor(connected_ns=time.perf_counter_ns())
        capture_queue: queue.Queue[bytes] = queue.Queue(
            maxsize=CAPTURE_QUEUE_BLOCKS
        )
        playback = _PlaybackFifo()
        failures: queue.Queue[_WorkerFailure] = queue.Queue(maxsize=1)
        send_lock = threading.Lock()
        workers: list[threading.Thread] = []
        transport_error: Exception | None = None

        try:
            # Capture stays on this coordinator. A dedicated playback worker is
            # the sole owner of the independent blocking output stream.
            try:
                input_stream = sd.RawInputStream(
                    samplerate=audio.input_native_rate,
                    blocksize=frames,
                    device=audio.input_index,
                    channels=CHANNELS,
                    dtype="int16",
                    extra_settings=getattr(audio, "input_extra_settings", None),
                )
            except Exception as exc:
                raise self._audio_stream_open_error(
                    direction="INPUT",
                    endpoint=audio.input_endpoint,
                    device_index=audio.input_index,
                    native_rate=audio.input_native_rate,
                    plan=audio.input_rate_plan,
                    error=exc,
                ) from exc
            with input_stream as stream:
                workers = [
                    threading.Thread(
                        target=self._send_worker,
                        args=(
                            ws,
                            stop_event,
                            capture_queue,
                            diagnostics,
                            failures,
                            send_lock,
                            monitor,
                            flight_context_gate,
                            model,
                            voice,
                        ),
                        daemon=True,
                        name="orion-qwen-send",
                    ),
                    threading.Thread(
                        target=self._receive_worker,
                        args=(
                            ws,
                            websocket,
                            provider,
                            audio,
                            stop_event,
                            playback,
                            diagnostics,
                            failures,
                            monitor,
                        ),
                        daemon=True,
                        name="orion-qwen-receive",
                    ),
                    threading.Thread(
                        target=self._playback_worker,
                        args=(
                            sd,
                            audio,
                            stop_event,
                            playback,
                            diagnostics,
                            failures,
                        ),
                        daemon=True,
                        name="orion-qwen-playback",
                    ),
                ]
                if ENABLE_QWEN_HEARTBEAT:
                    workers.append(
                        threading.Thread(
                            target=self._heartbeat_worker,
                            args=(
                                ws,
                                stop_event,
                                diagnostics,
                                failures,
                                send_lock,
                                monitor,
                            ),
                            daemon=True,
                            name="orion-qwen-heartbeat",
                        )
                    )
                for worker in workers:
                    worker.start()
                self._set(
                    state=QwenLiveState.STREAMING,
                    phase=QwenAudioPhase.LISTENING,
                    message="Qwen live audio streaming through blocking PortAudio input/output streams",
                )

                while not stop_event.is_set():
                    loop_start_ns = time.perf_counter_ns()
                    read_start_ns = time.perf_counter_ns()
                    raw, overflowed = stream.read(frames)
                    read_end_ns = time.perf_counter_ns()
                    diagnostics.record_capture(
                        read_start_ns=read_start_ns,
                        read_end_ns=read_end_ns,
                        frames_requested=frames,
                        frames_returned=len(raw) // 2,
                        overflow=bool(overflowed),
                    )
                    input_resample_start_ns = time.perf_counter_ns()
                    physical_pcm = bytes(raw)
                    # Preserve captured bytes on the protocol-native reference
                    # path. The existing resampler remains fallback-only.
                    qwen_pcm = (
                        physical_pcm
                        if audio.input_native_rate == QWEN_INPUT_RATE
                        else _resample_pcm16_mono(
                            physical_pcm,
                            audio.input_native_rate,
                            QWEN_INPUT_RATE,
                        )
                    )
                    input_rms, input_peak = _pcm16_mono_levels(physical_pcm)
                    input_resample_end_ns = time.perf_counter_ns()
                    diagnostics.record_input_levels(
                        t_ns=input_resample_end_ns,
                        rms=input_rms,
                        peak=input_peak,
                    )
                    capture_depth, dropped_capture_bytes = _put_drop_oldest(
                        capture_queue, qwen_pcm
                    )
                    diagnostics.record(
                        "capture_queue_enqueue",
                        t_ns=input_resample_end_ns,
                        depth=capture_depth,
                        capacity=CAPTURE_QUEUE_BLOCKS,
                    )
                    if dropped_capture_bytes:
                        diagnostics.record_queue_overflow(
                            channel="capture_queue",
                            dropped_bytes=dropped_capture_bytes,
                            sample_rate=QWEN_INPUT_RATE,
                            depth=capture_depth,
                            capacity=CAPTURE_QUEUE_BLOCKS,
                        )
                    # Correlation is a side channel: enqueue the exact live PCM
                    # first so diagnostic history cannot delay this send block.
                    self._record_microphone_analysis_pcm_safely(
                        diagnostics,
                        pcm=qwen_pcm,
                        sample_rate=QWEN_INPUT_RATE,
                        end_ns=read_end_ns,
                    )
                    with self._lock:
                        self._status.input_chunks += 1

                    loop_end_ns = time.perf_counter_ns()
                    diagnostics.record_loop(
                        loop_start_ns=loop_start_ns,
                        loop_end_ns=loop_end_ns,
                        read_ms=(read_end_ns - read_start_ns) / 1_000_000,
                        input_resample_ms=(
                            input_resample_end_ns - input_resample_start_ns
                        )
                        / 1_000_000,
                        send_ms=0.0,
                        recv_ms=0.0,
                        response_processing_ms=0.0,
                        write_ms=0.0,
                    )
        except Exception as exc:
            transport_error = exc
        finally:
            cleanup_ns = time.perf_counter_ns()
            diagnostics.record_websocket_event(
                "AUDIO_COORDINATOR_CLEANUP_START",
                direction="lifecycle",
                t_ns=cleanup_ns,
                stop_event_before=stop_event.is_set(),
                transport_error_type=(
                    type(transport_error).__name__ if transport_error else ""
                ),
            )
            diagnostics.record_websocket_disconnect(
                t_ns=cleanup_ns,
                origin=(
                    "transport_error" if transport_error else "cleanup_after_stop"
                ),
            )
            stop_event.set()
            playback.stop()
            diagnostics.record_websocket_event(
                "STOP_EVENT_SET",
                direction="lifecycle",
                stage="audio_coordinator_cleanup",
                stop_event_after=stop_event.is_set(),
            )
            diagnostics.record_normal_close_start(t_ns=time.perf_counter_ns())
            try:
                ws.close()
            except Exception as exc:
                diagnostics.record_websocket_exception(
                    exc,
                    ws=ws,
                    stage="close",
                    fatal=False,
                )
            diagnostics.record_normal_close_end(t_ns=time.perf_counter_ns())
            for worker in workers:
                worker.join(timeout=WORKER_JOIN_TIMEOUT_S)
            alive_workers = [worker for worker in workers if worker.is_alive()]
            abort = getattr(ws, "abort", None)
            if alive_workers and callable(abort):
                diagnostics.record_emergency_abort_start(t_ns=time.perf_counter_ns())
                try:
                    abort()
                except Exception as exc:
                    diagnostics.record_websocket_exception(
                        exc,
                        ws=ws,
                        stage="close",
                        fatal=False,
                    )
                diagnostics.record_emergency_abort_end(t_ns=time.perf_counter_ns())
                for worker in alive_workers:
                    worker.join(timeout=WORKER_JOIN_TIMEOUT_S)
            diagnostics.record_websocket_event(
                "AUDIO_COORDINATOR_CLEANUP_END",
                direction="lifecycle",
                workers_alive=",".join(
                    worker.name for worker in workers if worker.is_alive()
                ),
            )

        alive_workers = [worker.name for worker in workers if worker.is_alive()]
        if alive_workers:
            raise RuntimeError(
                "Qwen transport workers did not stop: " + ", ".join(alive_workers)
            )
        try:
            failure = failures.get_nowait()
        except queue.Empty:
            failure = None
        if failure is not None:
            raise RuntimeError(
                f"Qwen {failure.stage} failed: "
                f"{type(failure.error).__name__}: {failure.error}"
            ) from failure.error
        if transport_error is not None:
            raise transport_error

    def _run(self, request: QwenLiveStartRequest, stop_event: threading.Event) -> None:
        ws = None
        flight_context_gate = FlightContextUpdateGate(QWEN_INSTRUCTIONS)
        initial_context = flight_context_gate.next_update(force=True)
        if initial_context is None:  # pragma: no cover - force always returns a snapshot
            raise RuntimeError("Initial FlightContext snapshot is unavailable")
        session_update = _audio_session_update(
            request.model,
            request.voice,
            instructions=initial_context.instructions,
        )
        turn_detection = session_update["session"]["turn_detection"]
        diagnostics = QwenLiveDiagnostics(
            model=request.model,
            region=request.region,
            vad_type=str(turn_detection["type"]),
            silence_duration_ms=int(turn_detection["silence_duration_ms"]),
            qwen_input_rate=QWEN_INPUT_RATE,
            qwen_output_rate=QWEN_OUTPUT_RATE,
        )
        with self._lock:
            self._active_diagnostics = diagnostics
        connect_started = False
        try:
            import sounddevice as sd
            import websocket

            resolve_start_ns = time.perf_counter_ns()
            try:
                audio = self._resolve_audio(sd)
            except AudioDeviceRateError as exc:
                self._record_audio_rate_error(diagnostics, exc)
                raise
            resolve_end_ns = time.perf_counter_ns()
            diagnostics.record(
                "audio_resolved",
                t_ns=resolve_end_ns,
                resolve_start_ns=resolve_start_ns,
                resolve_end_ns=resolve_end_ns,
                resolve_duration_ms=(resolve_end_ns - resolve_start_ns) / 1_000_000,
            )
            if audio.input_rate_plan is not None:
                self._record_audio_rate_plan(diagnostics, audio.input_rate_plan)
            if audio.output_rate_plan is not None:
                self._record_audio_rate_plan(diagnostics, audio.output_rate_plan)
            frames = max(1, round(audio.input_native_rate * CAPTURE_MS / 1000))
            diagnostics.update_audio_metadata(
                input_device=audio.input_endpoint.name,
                output_device=audio.output_endpoint.name,
                input_native_rate=audio.input_native_rate,
                output_native_rate=audio.output_native_rate,
                duplex_rate=(
                    audio.input_native_rate
                    if audio.input_native_rate == audio.output_native_rate
                    else None
                ),
                block_frames=frames,
                block_duration_ms=CAPTURE_MS,
                input_rate_plan=audio.input_rate_plan,
                output_rate_plan=audio.output_rate_plan,
            )
            self._set(
                message="Opening Qwen realtime session",
                input_name=(
                    f"{audio.input_endpoint.name} "
                    f"[{getattr(audio.input_endpoint, 'host_api_name', 'PortAudio')}] "
                    f"(#{getattr(audio.input_endpoint, 'device_index', '?')})"
                ),
                output_name=(
                    f"{audio.output_endpoint.name} "
                    f"[{getattr(audio.output_endpoint, 'host_api_name', 'PortAudio')}] "
                    f"(#{getattr(audio.output_endpoint, 'device_index', '?')})"
                ),
                input_native_rate=audio.input_native_rate,
                output_native_rate=audio.output_native_rate,
            )
            config = QwenRealtimeConfig(api_key=request.api_key, workspace_id=request.workspace_id,
                                        region=request.region, model=request.model, timeout_s=15.0)
            provider = QwenRealtimeProvider(config)
            connect_start_ns = time.perf_counter_ns()
            connect_started = True
            diagnostics.record_websocket_event(
                "CONNECT_START",
                direction="lifecycle",
                t_ns=connect_start_ns,
            )
            try:
                ws = provider._connect()
            except Exception as exc:
                diagnostics.record_websocket_exception(
                    exc,
                    ws=None,
                    stage="connect",
                    fatal=True,
                )
                raise
            connect_end_ns = time.perf_counter_ns()
            diagnostics.record_websocket_connect(t_ns=connect_end_ns)
            monitor = _SessionMonitor(connected_ns=connect_end_ns)
            diagnostics.record(
                "ws_connected",
                t_ns=connect_end_ns,
                connect_start_ns=connect_start_ns,
                connect_end_ns=connect_end_ns,
                connect_duration_ms=(connect_end_ns - connect_start_ns) / 1_000_000,
            )
            diagnostics.record_websocket_ping_configuration(
                configured=ENABLE_QWEN_HEARTBEAT
            )
            _install_websocket_frame_telemetry(
                ws, websocket, diagnostics, monitor
            )
            session_send_start_ns = time.perf_counter_ns()
            diagnostics.record_websocket_event(
                "SESSION_UPDATE_SEND_START",
                direction="send",
                operation="send",
                t_ns=session_send_start_ns,
                event_type="session.update",
            )
            try:
                ws.send(json.dumps(session_update, ensure_ascii=False))
            except Exception as exc:
                diagnostics.record_websocket_exception(
                    exc,
                    ws=ws,
                    stage="send",
                    fatal=True,
                )
                raise
            session_send_end_ns = time.perf_counter_ns()
            monitor.record_tx(session_send_end_ns)
            diagnostics.record_websocket_event(
                "SESSION_UPDATE_SENT",
                direction="send",
                operation="send",
                t_ns=session_send_end_ns,
                event_type="session.update",
            )
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
                diagnostics.record_websocket_event(
                    "RECV_EVENT_START",
                    direction="recv",
                    operation="recv",
                    t_ns=recv_start_ns,
                    stage="session_handshake",
                )
                try:
                    event = provider._receive_json(ws)
                except websocket.WebSocketTimeoutException as exc:
                    recv_end_ns = time.perf_counter_ns()
                    diagnostics.record_websocket_exception(
                        exc,
                        ws=ws,
                        stage="recv",
                        fatal=False,
                        t_ns=recv_end_ns,
                    )
                    diagnostics.record_recv(
                        recv_start_ns=recv_start_ns,
                        recv_end_ns=recv_end_ns,
                        timeout=True,
                    )
                    continue
                recv_end_ns = time.perf_counter_ns()
                event_type = str(event.get("type") or "")
                diagnostics.record_websocket_event(
                    "RECV_EVENT_SUCCESS",
                    direction="recv",
                    operation="recv",
                    t_ns=recv_end_ns,
                    event_type=event_type,
                    stage="session_handshake",
                )
                diagnostics.record_recv(
                    recv_start_ns=recv_start_ns,
                    recv_end_ns=recv_end_ns,
                    timeout=False,
                    event_type=event_type,
                )
                if event_type == "error":
                    diagnostics.record_websocket_event(
                        "CONNECTION_CLASSIFIED",
                        direction="lifecycle",
                        classification="PROVIDER_ERROR_EVENT",
                    )
                    raise _ProviderErrorEvent(provider._error_message(event))
                if event_type == "session.updated":
                    diagnostics.record_websocket_session_ready(t_ns=recv_end_ns)
                    count = flight_context_gate.mark_applied(initial_context)
                    diagnostics.record(
                        "flight_context_applied",
                        context_state=initial_context.state.value,
                        context_fresh=initial_context.fresh,
                        aircraft_type=initial_context.aircraft_type,
                        context_generation=initial_context.generation,
                        context_update_count=count,
                        provider="qwen",
                    )
                    break
            else:
                raise TimeoutError("Timed out waiting for Qwen session.updated")

            ws.settimeout(None)
            diagnostics.record_transport_configuration(
                runtime_socket_timeout=None,
                enable_multithread=True,
                heartbeat_enabled=ENABLE_QWEN_HEARTBEAT,
                response_watchdog_enabled=ENABLE_QWEN_RESPONSE_WATCHDOG,
            )
            diagnostics.record("ws_runtime_blocking_configured", timeout=None)

            self._set(
                state=QwenLiveState.CONNECTED,
                message="Qwen connected; opening independent PortAudio audio streams",
            )
            try:
                self._run_transport(
                    sd=sd,
                    websocket=websocket,
                    ws=ws,
                    provider=provider,
                    audio=audio,
                    frames=frames,
                    stop_event=stop_event,
                    diagnostics=diagnostics,
                    monitor=monitor,
                    flight_context_gate=flight_context_gate,
                    model=request.model,
                    voice=request.voice,
                )
            finally:
                # _run_transport closes the socket to wake and join both network
                # workers. Handshake failures are still closed by the outer finally.
                ws = None

        except Exception as exc:
            if connect_started and not diagnostics.websocket_disconnect_recorded:
                diagnostics.record_websocket_exception(
                    exc,
                    ws=ws,
                    stage="session",
                    fatal=True,
                )
            diagnostics.record("session_error", error_type=type(exc).__name__)
            self._set(state=QwenLiveState.ERROR, phase=QwenAudioPhase.IDLE, message=f"{type(exc).__name__}: {exc}")
        finally:
            stop_event.set()
            if ws is not None:
                close_start_ns = time.perf_counter_ns()
                diagnostics.record_websocket_disconnect(
                    t_ns=close_start_ns,
                    origin="session_cleanup",
                )
                diagnostics.record_normal_close_start(t_ns=close_start_ns)
                try:
                    ws.close()
                except Exception as exc:
                    diagnostics.record_websocket_exception(
                        exc,
                        ws=ws,
                        stage="close",
                        fatal=False,
                    )
                diagnostics.record_normal_close_end(t_ns=time.perf_counter_ns())
            with self._lock:
                if self._status.state is not QwenLiveState.ERROR:
                    self._status.state = QwenLiveState.STOPPED
                    self._status.phase = QwenAudioPhase.IDLE
                    self._status.message = "Qwen live audio stopped"
            try:
                diagnostics.finish()
            except Exception:
                pass
            with self._lock:
                if self._active_diagnostics is diagnostics:
                    self._active_diagnostics = None


qwen_live_audio = QwenLiveAudioService()
