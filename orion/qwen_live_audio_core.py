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
from orion.qwen_live_diagnostics import QwenLiveDiagnostics
from orion.qwen_realtime_provider import QwenRealtimeConfig, QwenRealtimeProvider
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint

QWEN_INPUT_RATE = 16_000
QWEN_OUTPUT_RATE = 24_000
CHANNELS = 1
CAPTURE_MS = 40
CAPTURE_QUEUE_BLOCKS = 25
PLAYBACK_BUFFER_MS = 2_000
WORKER_JOIN_TIMEOUT_S = 1.0
PING_INTERVAL_SEC = 15.0
PONG_TIMEOUT_SEC = 10.0
FIRST_AUDIO_TIMEOUT_SEC = 20.0
INTER_DELTA_TIMEOUT_SEC = 5.0
RESPONSE_COMPLETION_TIMEOUT_SEC = 30.0


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


@dataclass(slots=True, frozen=True)
class _PlaybackBlock:
    pcm: bytes
    buffer_before_bytes: int
    buffer_after_bytes: int
    response_audio_frames: int
    zero_frames: int
    response_active: bool


class _BoundedPlaybackBuffer:
    """Thread-safe continuous PCM buffer with a drop-oldest size bound."""

    def __init__(self, max_bytes: int) -> None:
        if max_bytes <= 0 or max_bytes % 2:
            raise ValueError("Playback buffer size must be a positive PCM16 byte count")
        self.max_bytes = max_bytes
        self._data = bytearray()
        self._response_active = False
        self._lock = threading.Lock()

    def mark_response_active(self, active: bool) -> None:
        with self._lock:
            self._response_active = active

    def append(self, pcm: bytes) -> tuple[int, int, int]:
        if len(pcm) % 2:
            raise ValueError("Playback PCM must contain complete int16 samples")
        with self._lock:
            before = len(self._data)
            dropped = max(0, before + len(pcm) - self.max_bytes)
            if dropped:
                buffered_drop = min(dropped, before)
                del self._data[:buffered_drop]
                pcm = pcm[dropped - buffered_drop :]
            self._data.extend(pcm)
            return before, len(self._data), dropped

    def take_block(self, frames: int) -> _PlaybackBlock:
        bytes_needed = frames * 2
        with self._lock:
            before = len(self._data)
            response_active = self._response_active or before > 0
            if before >= bytes_needed:
                response_pcm = bytes(self._data[:bytes_needed])
                del self._data[:bytes_needed]
            elif before and not self._response_active:
                response_pcm = bytes(self._data)
                self._data.clear()
            else:
                # Hold a short provider delta for the next block instead of
                # padding each delta and inserting silence between valid PCM.
                response_pcm = b""
            after = len(self._data)
        response_frames = len(response_pcm) // 2
        zero_frames = frames - response_frames
        return _PlaybackBlock(
            pcm=response_pcm + b"\x00" * (zero_frames * 2),
            buffer_before_bytes=before,
            buffer_after_bytes=after,
            response_audio_frames=response_frames,
            zero_frames=zero_frames,
            response_active=response_active,
        )


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

    def _send_worker(
        self,
        ws: Any,
        stop_event: threading.Event,
        capture_queue: queue.Queue[bytes],
        diagnostics: QwenLiveDiagnostics,
        failures: queue.Queue[_WorkerFailure],
        send_lock: threading.Lock,
        monitor: _SessionMonitor,
    ) -> None:
        diagnostics.record("worker_started", stage="websocket_send")
        try:
            while not stop_event.is_set():
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
        playback: _BoundedPlaybackBuffer,
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

    def _receive_worker(
        self,
        ws: Any,
        websocket: Any,
        provider: QwenRealtimeProvider,
        audio: _ResolvedAudio,
        stop_event: threading.Event,
        playback: _BoundedPlaybackBuffer,
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
                    self._apply_response_timeout(
                        monitor=monitor,
                        now_ns=recv_end_ns,
                        playback=playback,
                        diagnostics=diagnostics,
                    )
                    continue
                recv_end_ns = time.perf_counter_ns()
                monitor.record_rx(recv_end_ns)
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
                if event_type == "response.audio.delta" and isinstance(
                    event.get("delta"), str
                ):
                    encoded_delta = event["delta"]
                    decoded_delta = base64.b64decode(encoded_delta)
                    response_resample_start_ns = time.perf_counter_ns()
                    resampled_delta = _resample_pcm16_mono(
                        decoded_delta, QWEN_OUTPUT_RATE, audio.native_rate
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
                        target_rate=audio.native_rate,
                    )
                    playback.mark_response_active(True)
                    before_bytes, after_bytes, dropped_bytes = playback.append(
                        resampled_delta
                    )
                    diagnostics.record_playback_enqueue(
                        t_ns=response_resample_end_ns,
                        before_bytes=before_bytes,
                        after_bytes=after_bytes,
                        sample_rate=audio.native_rate,
                        added_bytes=len(resampled_delta),
                    )
                    if dropped_bytes:
                        diagnostics.record_queue_overflow(
                            channel="playback_buffer",
                            dropped_bytes=dropped_bytes,
                            sample_rate=audio.native_rate,
                            depth=after_bytes,
                            capacity=playback.max_bytes,
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
    ) -> None:
        if monitor is None:
            monitor = _SessionMonitor(connected_ns=time.perf_counter_ns())
        capture_queue: queue.Queue[bytes] = queue.Queue(
            maxsize=CAPTURE_QUEUE_BLOCKS
        )
        playback = _BoundedPlaybackBuffer(
            max_bytes=max(
                frames * 2,
                round(audio.native_rate * PLAYBACK_BUFFER_MS / 1000) * 2,
            )
        )
        failures: queue.Queue[_WorkerFailure] = queue.Queue(maxsize=1)
        send_lock = threading.Lock()
        workers: list[threading.Thread] = []
        settings = sd.WasapiSettings(exclusive=False)
        transport_error: Exception | None = None

        try:
            # One blocking PaStream and one calling thread own both WASAPI
            # endpoints. Network send/receive never execute on this thread.
            with sd.RawStream(
                samplerate=audio.native_rate,
                blocksize=frames,
                device=(audio.input_index, audio.output_index),
                channels=(CHANNELS, CHANNELS),
                dtype=("int16", "int16"),
                extra_settings=(settings, settings),
            ) as stream:
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
                    ),
                ]
                for worker in workers:
                    worker.start()
                self._set(
                    state=QwenLiveState.STREAMING,
                    phase=QwenAudioPhase.LISTENING,
                    message="Qwen live audio streaming through one WASAPI duplex stream",
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
                    qwen_pcm = _resample_pcm16_mono(
                        bytes(raw), audio.native_rate, QWEN_INPUT_RATE
                    )
                    input_resample_end_ns = time.perf_counter_ns()
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
                    with self._lock:
                        self._status.input_chunks += 1

                    block = playback.take_block(frames)
                    write_start_ns = time.perf_counter_ns()
                    underflowed = stream.write(block.pcm)
                    write_end_ns = time.perf_counter_ns()
                    if block.response_audio_frames:
                        with self._lock:
                            self._status.output_chunks += 1
                    diagnostics.record_write(
                        write_start_ns=write_start_ns,
                        write_end_ns=write_end_ns,
                        buffer_before_bytes=block.buffer_before_bytes,
                        buffer_after_bytes=block.buffer_after_bytes,
                        response_audio_frames=block.response_audio_frames,
                        zero_frames=block.zero_frames,
                        frames_written=frames,
                        sample_rate=audio.native_rate,
                        underflow=bool(underflowed),
                        response_active=block.response_active,
                    )
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
                        write_ms=(write_end_ns - write_start_ns) / 1_000_000,
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
            diagnostics.record_websocket_event(
                "STOP_EVENT_SET",
                direction="lifecycle",
                stage="audio_coordinator_cleanup",
                stop_event_after=stop_event.is_set(),
            )
            abort = getattr(ws, "abort", None)
            if callable(abort):
                diagnostics.record_websocket_event(
                    "WEBSOCKET_ABORT_START",
                    direction="close",
                    operation="close",
                )
                try:
                    abort()
                except Exception as exc:
                    diagnostics.record_websocket_exception(
                        exc,
                        ws=ws,
                        stage="close",
                        fatal=False,
                    )
                diagnostics.record_websocket_event(
                    "WEBSOCKET_ABORT_END",
                    direction="close",
                    operation="close",
                )
            diagnostics.record_websocket_close_attempt(
                t_ns=time.perf_counter_ns()
            )
            try:
                ws.close()
            except Exception as exc:
                diagnostics.record_websocket_exception(
                    exc,
                    ws=ws,
                    stage="close",
                    fatal=False,
                )
            diagnostics.record_websocket_event(
                "WEBSOCKET_CLOSE_END",
                direction="close",
                operation="close",
                close_frame_received=diagnostics.websocket_forensics()[
                    "close_frame_received"
                ],
            )
            for worker in workers:
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
        with self._lock:
            self._active_diagnostics = diagnostics
        connect_started = False
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
            diagnostics.record_websocket_ping_configuration(configured=True)
            _install_websocket_frame_telemetry(
                ws, websocket, diagnostics, monitor
            )
            ws.settimeout(0.25)
            diagnostics.record("ws_timeout_configured", timeout_ms=250)
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
            self._set(
                state=QwenLiveState.CONNECTED,
                message="Qwen connected; opening one full-duplex WASAPI stream",
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
                diagnostics.record_websocket_close_attempt(t_ns=close_start_ns)
                try:
                    ws.close()
                except Exception as exc:
                    diagnostics.record_websocket_exception(
                        exc,
                        ws=ws,
                        stage="close",
                        fatal=False,
                    )
                diagnostics.record_websocket_event(
                    "WEBSOCKET_CLOSE_END",
                    direction="close",
                    operation="close",
                )
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
