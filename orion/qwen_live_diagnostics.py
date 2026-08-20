from __future__ import annotations

import json
import math
import os
import socket
import statistics
import threading
import time
import traceback
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Concatenate, ParamSpec, TypeVar


DEFAULT_MAX_EVENTS = 20_000
DEFAULT_MAX_TIMING_SAMPLES = 10_000
DEFAULT_WEBSOCKET_RING_EVENTS = 100
EFFECTIVE_SILENCE_PEAK = 0.001

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _synchronized(
    method: Callable[Concatenate[Any, _P], _R],
) -> Callable[Concatenate[Any, _P], _R]:
    @wraps(method)
    def wrapped(self: Any, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped

_FORBIDDEN_FIELD_NAMES = {
    "api_key",
    "authorization",
    "audio",
    "base64",
    "delta",
    "payload",
    "raw",
}


class QwenLiveDiagnostics:
    """Bounded, thread-safe timing recorder for the Qwen Live transport."""

    def __init__(
        self,
        *,
        model: str,
        region: str,
        vad_type: str,
        silence_duration_ms: int,
        qwen_input_rate: int,
        qwen_output_rate: int,
        runtime_dir: Path | None = None,
        max_events: int = DEFAULT_MAX_EVENTS,
        max_timing_samples: int = DEFAULT_MAX_TIMING_SAMPLES,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
        start_ns: int | None = None,
        start_utc: datetime | None = None,
        session_id: str | None = None,
    ) -> None:
        if max_events <= 0 or max_timing_samples <= 0:
            raise ValueError("Diagnostic buffer limits must be positive")
        self._lock = threading.RLock()
        self._clock_ns = clock_ns
        self.start_ns = clock_ns() if start_ns is None else start_ns
        self.start_utc = start_utc or datetime.now(UTC)
        self.session_id = session_id or uuid.uuid4().hex[:12]
        base = runtime_dir or Path(os.environ.get("ORION_RUNTIME_DIR", "runtime"))
        self.output_dir = base / "qwen-live"
        self._events: deque[dict[str, object]] = deque(maxlen=max_events)
        self._websocket_events: deque[dict[str, object]] = deque(
            maxlen=DEFAULT_WEBSOCKET_RING_EVENTS
        )
        self._websocket_connect_ns: int | None = None
        self._websocket_session_ready_ns: int | None = None
        self._websocket_disconnect_ns: int | None = None
        self._websocket_close_ns: int | None = None
        self._websocket_close_code: int | None = None
        self._websocket_close_reason = ""
        self._websocket_close_frame_received = False
        self._websocket_clean_close = False
        self._websocket_disconnect_origin = ""
        self._websocket_exception: dict[str, object] | None = None
        self._websocket_ping_configured = False
        self._runtime_socket_timeout: float | None = None
        self._enable_multithread = False
        self._heartbeat_enabled = False
        self._response_watchdog_enabled = False
        self._normal_close_called = False
        self._emergency_abort_called = False
        self._websocket_send_thread_ids: set[int] = set()
        self._websocket_recv_thread_ids: set[int] = set()
        self._websocket_close_thread_ids: set[int] = set()
        self._max_events = max_events
        self._dropped_events = 0
        self._max_timing_samples = max_timing_samples
        self._timing_samples: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self._max_timing_samples)
        )
        self._timing_counts: dict[str, int] = defaultdict(int)
        self._timing_sums: dict[str, float] = defaultdict(float)
        self._timing_maxima: dict[str, float] = defaultdict(float)
        self._timing_dropped: dict[str, int] = defaultdict(int)
        self._metadata: dict[str, object] = {
            "session_id": self.session_id,
            "utc_start": self.start_utc.isoformat(),
            "monotonic_start_ns": self.start_ns,
            "model": model,
            "region": region,
            "vad_type": vad_type,
            "silence_duration_ms": silence_duration_ms,
            "qwen_input_rate": qwen_input_rate,
            "qwen_output_rate": qwen_output_rate,
        }
        self._first_capture_ns: int | None = None
        self._last_capture_ns: int | None = None
        self._first_send_ns: int | None = None
        self._last_send_ns: int | None = None
        self._captured_frames = 0
        self._sent_frames = 0
        self._capture_rate = 0
        self._send_rate = qwen_input_rate
        self._input_overflow_count = 0
        self._input_level_blocks = 0
        self._input_silent_blocks = 0
        self._input_rms_sum = 0.0
        self._input_rms_max = 0.0
        self._input_peak_max = 0.0
        self._output_underflow_count = 0
        self._recv_call_count = 0
        self._recv_timeout_count = 0
        self._response_index = 0
        self._response_active = False
        self._current_response_has_audio = False
        self._previous_received_event_type = ""
        self._consecutive_audio_delta_events = 0
        self._maximum_consecutive_audio_delta_events = 0
        self._near_zero_wait_audio_delta_count = 0
        self._audio_delta_count = 0
        self._provider_delta_bytes = 0
        self._previous_audio_delta_ns: int | None = None
        self._first_audio_delta_session_ns: int | None = None
        self._last_audio_delta_session_ns: int | None = None
        self._decoded_response_audio_ms = 0.0
        self._resampled_response_audio_ms = 0.0
        self._first_markers: dict[str, int] = {}
        self._maximum_playback_backlog_ms = 0.0
        self._minimum_playback_backlog_active_ms: float | None = None
        self._enqueued_response_audio_ms = 0.0
        self._non_silent_audio_written_ms = 0.0
        self._non_silent_write_count = 0
        self._active_response_write_count = 0
        self._previous_active_write_start_ns: int | None = None
        self._previous_non_silent_write_start_ns: int | None = None
        self._previous_non_silent_write_end_ns: int | None = None
        self._response_period_start_ns: int | None = None
        self._response_period_closed_ns = 0
        self._starvation_start_ns: int | None = None
        self._playback_wait_start_ns: int | None = None
        self._starvation_closed_count = 0
        self._starvation_closed_ns = 0
        self._starvation_max_closed_ns = 0
        self._playback_buffer_zero_active_count = 0
        self._insufficient_audio_cycles = 0
        self._zero_padded_write_count = 0
        self._partial_zero_padded_write_count = 0
        self._fully_silent_active_write_count = 0
        self._zero_padding_frames = 0
        self._zero_padded_after_recv_timeout_count = 0
        self._starved_after_recv_timeout_count = 0
        self._queue_overflow_counts: dict[str, int] = defaultdict(int)
        self._queue_dropped_bytes: dict[str, int] = defaultdict(int)
        self._queue_dropped_audio_ms: dict[str, float] = defaultdict(float)
        self._duplex_rate = 0
        self.record("session_start", t_ns=self.start_ns)

    @property
    @_synchronized
    def event_count(self) -> int:
        return len(self._events)

    @property
    @_synchronized
    def dropped_event_count(self) -> int:
        return self._dropped_events

    @property
    @_synchronized
    def response_active(self) -> bool:
        return self._response_active

    @property
    @_synchronized
    def response_index(self) -> int:
        return self._response_index

    @property
    @_synchronized
    def websocket_disconnect_recorded(self) -> bool:
        return self._websocket_disconnect_ns is not None

    @property
    @_synchronized
    def websocket_clean_close(self) -> bool:
        return (
            self._websocket_close_frame_received and self._websocket_clean_close
        )

    @_synchronized
    def update_audio_metadata(
        self,
        *,
        input_device: str,
        output_device: str,
        input_native_rate: int,
        output_native_rate: int,
        duplex_rate: int | None,
        block_frames: int,
        block_duration_ms: float,
        input_rate_plan: object | None = None,
        output_rate_plan: object | None = None,
    ) -> None:
        self._capture_rate = input_native_rate
        self._duplex_rate = duplex_rate or output_native_rate
        audio_devices: dict[str, dict[str, object]] = {}
        for direction, plan in (
            ("input", input_rate_plan),
            ("output", output_rate_plan),
        ):
            if plan is None:
                continue
            rejected = [
                {
                    "rate": getattr(item, "rate", None),
                    "error_type": str(getattr(item, "error_type", "")),
                    "message": str(getattr(item, "message", "")),
                }
                for item in getattr(plan, "rejected_rates", ())
            ]
            audio_devices[direction] = {
                "logical_device_id": str(
                    getattr(plan, "logical_device_id", "")
                ),
                "device_index": getattr(plan, "device_index", None),
                "device_name": str(getattr(plan, "device_name", "")),
                "host_api": str(getattr(plan, "host_api", "")),
                "reported_default_samplerate": getattr(
                    plan, "default_rate", None
                ),
                "attempted_rates": list(
                    getattr(plan, "attempted_rates", ())
                ),
                "rejected_rates": rejected,
                "selected_native_rate": getattr(plan, "physical_rate", None),
                "protocol_rate": getattr(plan, "protocol_rate", None),
                "resampling_required": bool(
                    getattr(plan, "resampling_required", False)
                ),
            }
        self._metadata.update(
            {
                "input_device": input_device,
                "output_device": output_device,
                "input_native_rate": input_native_rate,
                "output_native_rate": output_native_rate,
                "duplex_rate": duplex_rate,
                "block_frames": block_frames,
                "block_duration_ms": block_duration_ms,
                "audio_devices": audio_devices,
            }
        )
        self.record("audio_metadata_ready")

    @_synchronized
    def record_input_levels(self, *, t_ns: int, rms: float, peak: float) -> None:
        self._input_level_blocks += 1
        silent = peak < EFFECTIVE_SILENCE_PEAK
        self._input_silent_blocks += int(silent)
        self._input_rms_sum += rms
        self._input_rms_max = max(self._input_rms_max, rms)
        self._input_peak_max = max(self._input_peak_max, peak)
        if self._input_level_blocks == 1 or self._input_level_blocks % 25 == 0:
            self.record(
                "input_level_aggregate",
                t_ns=t_ns,
                capture_block_count=self._input_level_blocks,
                rms=rms,
                peak=peak,
                effectively_silent=silent,
                silent_block_count=self._input_silent_blocks,
            )

    @_synchronized
    def record(self, kind: str, *, t_ns: int | None = None, **fields: object) -> None:
        safe_fields: dict[str, object] = {}
        for key, value in fields.items():
            if key.casefold() in _FORBIDDEN_FIELD_NAMES:
                continue
            if isinstance(value, (bytes, bytearray, memoryview)):
                continue
            if value is None or isinstance(value, (str, int, float, bool)):
                safe_fields[key] = value
        if len(self._events) == self._max_events:
            self._dropped_events += 1
        self._events.append(
            {
                "kind": kind,
                "t_ns": self._clock_ns() if t_ns is None else t_ns,
                **safe_fields,
            }
        )

    def _utc_timestamp(self, t_ns: int) -> str:
        return (
            self.start_utc
            + timedelta(seconds=(t_ns - self.start_ns) / 1_000_000_000)
        ).isoformat()

    @_synchronized
    def record_websocket_event(
        self,
        event: str,
        *,
        direction: str,
        t_ns: int | None = None,
        operation: str = "",
        **fields: object,
    ) -> None:
        event_ns = self._clock_ns() if t_ns is None else t_ns
        thread_id = threading.get_ident()
        if operation == "send":
            self._websocket_send_thread_ids.add(thread_id)
        elif operation == "recv":
            self._websocket_recv_thread_ids.add(thread_id)
        elif operation == "close":
            self._websocket_close_thread_ids.add(thread_id)
        safe_fields: dict[str, object] = {}
        for key, value in fields.items():
            if key.casefold() in _FORBIDDEN_FIELD_NAMES:
                continue
            if isinstance(value, (bytes, bytearray, memoryview)):
                continue
            if value is None or isinstance(value, (str, int, float, bool)):
                safe_fields[key] = value
        self._websocket_events.append(
            {
                "timestamp": self._utc_timestamp(event_ns),
                "t_ns": event_ns,
                "event": event,
                "event_type": str(safe_fields.pop("event_type", "")),
                "thread_name": threading.current_thread().name,
                "thread_id": thread_id,
                "direction": direction,
                **safe_fields,
            }
        )

    @_synchronized
    def record_websocket_connect(self, *, t_ns: int) -> None:
        self._websocket_connect_ns = t_ns
        self.record_websocket_event(
            "CONNECT_SUCCESS", direction="lifecycle", t_ns=t_ns
        )

    @_synchronized
    def record_websocket_session_ready(self, *, t_ns: int) -> None:
        self._websocket_session_ready_ns = t_ns
        self.record_websocket_event(
            "SESSION_UPDATE_RECEIVED",
            direction="recv",
            operation="recv",
            t_ns=t_ns,
            event_type="session.updated",
        )

    @_synchronized
    def record_websocket_ping_configuration(self, *, configured: bool) -> None:
        self._websocket_ping_configured = configured
        self.record_websocket_event(
            "PING_CONFIGURED" if configured else "PING_NOT_CONFIGURED",
            direction="lifecycle",
            configured=configured,
        )

    @_synchronized
    def record_transport_configuration(
        self,
        *,
        runtime_socket_timeout: float | None,
        enable_multithread: bool,
        heartbeat_enabled: bool,
        response_watchdog_enabled: bool,
    ) -> None:
        self._runtime_socket_timeout = runtime_socket_timeout
        self._enable_multithread = enable_multithread
        self._heartbeat_enabled = heartbeat_enabled
        self._response_watchdog_enabled = response_watchdog_enabled
        self.record_websocket_event(
            "TRANSPORT_CONFIGURATION",
            direction="lifecycle",
            runtime_socket_timeout=runtime_socket_timeout,
            enable_multithread=enable_multithread,
            heartbeat_enabled=heartbeat_enabled,
            response_watchdog_enabled=response_watchdog_enabled,
        )

    @_synchronized
    def record_websocket_close_frame(self, frame_data: bytes, *, t_ns: int) -> None:
        code: int | None = None
        reason = ""
        if len(frame_data) >= 2:
            code = int.from_bytes(frame_data[:2], "big")
            reason = frame_data[2:].decode("utf-8", errors="replace")
        self._websocket_close_ns = t_ns
        self._websocket_close_code = code
        self._websocket_close_reason = reason
        self._websocket_close_frame_received = True
        self._websocket_clean_close = code in {1000, 1001}
        self.record_websocket_event(
            "WEBSOCKET_CLOSE_RECEIVED",
            direction="recv",
            operation="recv",
            t_ns=t_ns,
            close_code=code,
            close_reason=reason,
            clean_close=self._websocket_clean_close,
            close_frame_received=True,
        )

    @_synchronized
    def record_websocket_close_attempt(self, *, t_ns: int) -> None:
        if self._websocket_close_ns is None:
            self._websocket_close_ns = t_ns
        self.record_websocket_event(
            "WEBSOCKET_CLOSE_START",
            direction="close",
            operation="close",
            t_ns=t_ns,
            close_frame_received=self._websocket_close_frame_received,
        )

    @_synchronized
    def record_normal_close_start(self, *, t_ns: int) -> None:
        self._normal_close_called = True
        if self._websocket_close_ns is None:
            self._websocket_close_ns = t_ns
        self.record_websocket_event(
            "NORMAL_CLOSE_START",
            direction="close",
            operation="close",
            t_ns=t_ns,
            close_frame_received=self._websocket_close_frame_received,
        )

    @_synchronized
    def record_normal_close_end(self, *, t_ns: int) -> None:
        self.record_websocket_event(
            "NORMAL_CLOSE_END",
            direction="close",
            operation="close",
            t_ns=t_ns,
            close_frame_received=self._websocket_close_frame_received,
        )

    @_synchronized
    def record_emergency_abort_start(self, *, t_ns: int) -> None:
        self._emergency_abort_called = True
        self.record_websocket_event(
            "EMERGENCY_ABORT_START",
            direction="close",
            operation="close",
            t_ns=t_ns,
        )

    @_synchronized
    def record_emergency_abort_end(self, *, t_ns: int) -> None:
        self.record_websocket_event(
            "EMERGENCY_ABORT_END",
            direction="close",
            operation="close",
            t_ns=t_ns,
        )

    @staticmethod
    def _underlying_exception(exc: BaseException) -> tuple[str, int | None]:
        parts: list[str] = []
        socket_errno = exc.errno if isinstance(exc, OSError) else None
        seen: set[int] = set()
        current = exc.__cause__ or exc.__context__
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            parts.append(f"{type(current).__name__}: {current}")
            if socket_errno is None and isinstance(current, OSError):
                socket_errno = current.errno
            current = current.__cause__ or current.__context__
        return " <- ".join(parts), socket_errno

    @staticmethod
    def _socket_errno(ws: Any, fallback: int | None) -> int | None:
        if fallback is not None:
            return fallback
        sock = getattr(ws, "sock", None)
        if sock is None:
            return None
        try:
            return int(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR))
        except (AttributeError, OSError, TypeError, ValueError):
            return None

    @_synchronized
    def record_websocket_exception(
        self,
        exc: BaseException,
        *,
        ws: Any,
        stage: str,
        fatal: bool,
        t_ns: int | None = None,
    ) -> None:
        event_ns = self._clock_ns() if t_ns is None else t_ns
        underlying, underlying_errno = self._underlying_exception(exc)
        details: dict[str, object] = {
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "full_traceback": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
            "underlying_exception": underlying,
            "socket_errno": self._socket_errno(ws, underlying_errno),
            "stage": stage,
            "fatal": fatal,
            "close_frame_received": self._websocket_close_frame_received,
            "close_code": self._websocket_close_code,
            "close_reason": self._websocket_close_reason,
        }
        if fatal or self._websocket_exception is None:
            self._websocket_exception = details
        self.record_websocket_event(
            "WEBSOCKET_EXCEPTION",
            direction=stage,
            operation="recv" if stage == "recv" else "send" if stage == "send" else "",
            t_ns=event_ns,
            **details,
        )
        if fatal:
            self.record_websocket_disconnect(
                t_ns=event_ns, origin=f"{stage}_exception"
            )

    @_synchronized
    def record_websocket_disconnect(self, *, t_ns: int, origin: str) -> None:
        if self._websocket_disconnect_ns is None:
            self._websocket_disconnect_ns = t_ns
            self._websocket_disconnect_origin = origin
        self.record_websocket_event(
            "WEBSOCKET_DISCONNECT",
            direction="lifecycle",
            t_ns=t_ns,
            disconnect_origin=origin,
            close_frame_received=self._websocket_close_frame_received,
            close_code=self._websocket_close_code,
            close_reason=self._websocket_close_reason,
            clean_close=self._websocket_clean_close,
        )

    @_synchronized
    def websocket_forensics(self) -> dict[str, object]:
        connection_duration_ms = self._optional_elapsed_ms(
            self._websocket_connect_ns, self._websocket_disconnect_ns
        )
        return {
            "connect_timestamp": self._utc_timestamp(self._websocket_connect_ns)
            if self._websocket_connect_ns is not None
            else None,
            "session_ready_timestamp": self._utc_timestamp(
                self._websocket_session_ready_ns
            )
            if self._websocket_session_ready_ns is not None
            else None,
            "disconnect_timestamp": self._utc_timestamp(
                self._websocket_disconnect_ns
            )
            if self._websocket_disconnect_ns is not None
            else None,
            "connection_duration_ms": connection_duration_ms,
            "close_timestamp": self._utc_timestamp(self._websocket_close_ns)
            if self._websocket_close_ns is not None
            else None,
            "close_code": self._websocket_close_code,
            "close_reason": self._websocket_close_reason,
            "clean_close": self._websocket_clean_close,
            "close_frame_received": self._websocket_close_frame_received,
            "disconnect_origin": self._websocket_disconnect_origin,
            "ping_configured": self._websocket_ping_configured,
            "runtime_socket_timeout": self._runtime_socket_timeout,
            "enable_multithread": self._enable_multithread,
            "heartbeat_enabled": self._heartbeat_enabled,
            "response_watchdog_enabled": self._response_watchdog_enabled,
            "normal_close_called": self._normal_close_called,
            "emergency_abort_called": self._emergency_abort_called,
            "exception": dict(self._websocket_exception)
            if self._websocket_exception is not None
            else None,
            "send_thread_ids": sorted(self._websocket_send_thread_ids),
            "recv_thread_ids": sorted(self._websocket_recv_thread_ids),
            "close_thread_ids": sorted(self._websocket_close_thread_ids),
            "recent_events": [dict(event) for event in self._websocket_events],
        }

    def _timing(self, stage: str, duration_ms: float) -> None:
        samples = self._timing_samples[stage]
        if len(samples) == self._max_timing_samples:
            self._timing_dropped[stage] += 1
        samples.append(duration_ms)
        self._timing_counts[stage] += 1
        self._timing_sums[stage] += duration_ms
        self._timing_maxima[stage] = max(self._timing_maxima[stage], duration_ms)

    def _start_response_period(self, t_ns: int) -> None:
        if self._response_period_start_ns is not None:
            self._close_response_period(t_ns)
        self._response_period_start_ns = t_ns
        self._previous_audio_delta_ns = None
        self._previous_active_write_start_ns = None
        self._previous_non_silent_write_start_ns = None
        self._previous_non_silent_write_end_ns = None

    def _close_response_period(self, t_ns: int) -> None:
        start_ns = self._response_period_start_ns
        if start_ns is not None and t_ns > start_ns:
            self._response_period_closed_ns += t_ns - start_ns
        self._response_period_start_ns = None
        self._previous_active_write_start_ns = None
        self._previous_non_silent_write_start_ns = None
        self._previous_non_silent_write_end_ns = None

    def _close_starvation(self, t_ns: int) -> None:
        start_ns = self._starvation_start_ns
        if start_ns is None:
            return
        duration_ns = max(0, t_ns - start_ns)
        duration_ms = duration_ns / 1_000_000
        self._starvation_closed_count += 1
        self._starvation_closed_ns += duration_ns
        self._starvation_max_closed_ns = max(
            self._starvation_max_closed_ns, duration_ns
        )
        self._timing("playback_starvation", duration_ms)
        self.record(
            "PLAYBACK_STARVATION_ENDED",
            t_ns=t_ns,
            starvation_start_ns=start_ns,
            starvation_duration_ms=duration_ms,
        )
        self._starvation_start_ns = None

    @staticmethod
    def _elapsed_ms(start_ns: int | None, end_ns: int | None) -> float:
        if start_ns is None or end_ns is None or end_ns <= start_ns:
            return 0.0
        return (end_ns - start_ns) / 1_000_000

    @staticmethod
    def _optional_elapsed_ms(
        start_ns: int | None, end_ns: int | None
    ) -> float | None:
        if start_ns is None or end_ns is None or end_ns <= start_ns:
            return None
        return (end_ns - start_ns) / 1_000_000

    @staticmethod
    def _ratio(audio_ms: float, wall_ms: float) -> float | None:
        return None if wall_ms <= 0 else audio_ms / wall_ms

    @staticmethod
    def playback_ms(byte_count: int, sample_rate: int) -> float:
        if sample_rate <= 0:
            return 0.0
        return max(0, byte_count) / 2 / sample_rate * 1000

    @_synchronized
    def record_capture(
        self,
        *,
        read_start_ns: int,
        read_end_ns: int,
        frames_requested: int,
        frames_returned: int,
        overflow: bool,
    ) -> None:
        if self._first_capture_ns is None:
            self._first_capture_ns = read_start_ns
        self._last_capture_ns = read_end_ns
        self._captured_frames += frames_returned
        if overflow:
            self._input_overflow_count += 1
        duration_ms = self._elapsed_ms(read_start_ns, read_end_ns)
        self._timing("stream_read", duration_ms)
        audio_ms = self.playback_ms(self._captured_frames * 2, self._capture_rate)
        wall_ms = self._elapsed_ms(self._first_capture_ns, read_end_ns)
        self.record(
            "stream_read",
            t_ns=read_end_ns,
            read_start_ns=read_start_ns,
            read_end_ns=read_end_ns,
            read_duration_ms=duration_ms,
            frames_requested=frames_requested,
            frames_returned=frames_returned,
            overflow=overflow,
            cumulative_captured_frames=self._captured_frames,
            cumulative_captured_audio_ms=audio_ms,
            cumulative_wall_ms=wall_ms,
            capture_realtime_ratio=self._ratio(audio_ms, wall_ms),
        )

    @_synchronized
    def record_send(
        self,
        *,
        send_start_ns: int,
        send_end_ns: int,
        pcm_frames: int,
    ) -> None:
        if self._first_send_ns is None:
            self._first_send_ns = send_start_ns
        self._last_send_ns = send_end_ns
        self._sent_frames += pcm_frames
        duration_ms = self._elapsed_ms(send_start_ns, send_end_ns)
        self._timing("ws_send", duration_ms)
        audio_ms = self.playback_ms(self._sent_frames * 2, self._send_rate)
        wall_ms = self._elapsed_ms(self._first_send_ns, send_end_ns)
        self.record(
            "input_audio_send",
            t_ns=send_end_ns,
            send_start_ns=send_start_ns,
            send_end_ns=send_end_ns,
            send_duration_ms=duration_ms,
            pcm_frames=pcm_frames,
            represented_audio_ms=self.playback_ms(pcm_frames * 2, self._send_rate),
            cumulative_sent_frames=self._sent_frames,
            cumulative_sent_audio_ms=audio_ms,
            cumulative_wall_ms=wall_ms,
            send_realtime_ratio=self._ratio(audio_ms, wall_ms),
        )

    @_synchronized
    def record_recv(
        self,
        *,
        recv_start_ns: int,
        recv_end_ns: int,
        timeout: bool,
        event_type: str = "",
    ) -> None:
        wait_ms = self._elapsed_ms(recv_start_ns, recv_end_ns)
        self._recv_call_count += 1
        if timeout:
            self._recv_timeout_count += 1
        self._timing("ws_recv", wait_ms)
        if event_type == "response.audio.delta":
            self._timing("audio_delta_recv_wait", wait_ms)
            if wait_ms <= 5.0:
                self._near_zero_wait_audio_delta_count += 1
            if self._previous_received_event_type == event_type:
                self._consecutive_audio_delta_events += 1
            else:
                self._consecutive_audio_delta_events = 1
            self._maximum_consecutive_audio_delta_events = max(
                self._maximum_consecutive_audio_delta_events,
                self._consecutive_audio_delta_events,
            )
        elif event_type:
            self._consecutive_audio_delta_events = 0
        if event_type:
            self._previous_received_event_type = event_type
        self.record(
            "ws_recv",
            t_ns=recv_end_ns,
            recv_start_ns=recv_start_ns,
            recv_end_ns=recv_end_ns,
            recv_wait_ms=wait_ms,
            timeout=timeout,
            event_type=event_type,
        )
        if event_type:
            self.record_provider_event(event_type, t_ns=recv_end_ns)

    @_synchronized
    def record_provider_event(self, event_type: str, *, t_ns: int) -> None:
        if event_type == "input_audio_buffer.speech_started":
            self._first_markers.setdefault("speech_started_ns", t_ns)
        elif event_type == "input_audio_buffer.speech_stopped":
            self._first_markers.setdefault("speech_stopped_ns", t_ns)
        if event_type == "response.created":
            self._response_index += 1
            self._response_active = True
            self._current_response_has_audio = False
            self._start_response_period(t_ns)
            self._first_markers.setdefault("first_response_event_ns", t_ns)
            if (
                self._playback_wait_start_ns is not None
                and self._starvation_start_ns is None
            ):
                self._starvation_start_ns = t_ns
                self.record(
                    "PLAYBACK_STARVATION_STARTED",
                    t_ns=t_ns,
                    response_index=self._response_index,
                )
        elif event_type.startswith("response."):
            self._first_markers.setdefault("first_response_event_ns", t_ns)
        if event_type in {"response.audio.done", "response.done"}:
            self._response_active = False
            self._close_starvation(t_ns)
        if event_type == "response.audio.done":
            self._first_markers.setdefault("response_audio_done_ns", t_ns)
        elif event_type == "response.done":
            self._first_markers.setdefault("response_done_ns", t_ns)
        self.record(
            "provider_event",
            t_ns=t_ns,
            event_type=event_type,
            response_index=self._response_index,
        )

    @_synchronized
    def record_audio_delta(
        self,
        *,
        receive_ns: int,
        encoded_chars: int,
        decoded_bytes: int,
        source_rate: int,
        resample_start_ns: int,
        resample_end_ns: int,
        resampled_bytes: int,
        target_rate: int,
    ) -> int:
        if not self._response_active:
            self._response_index += 1
            self._response_active = True
            self._current_response_has_audio = False
            self._start_response_period(receive_ns)
        elif self._response_period_start_ns is None:
            self._start_response_period(receive_ns)
        first_for_response = not self._current_response_has_audio
        self._current_response_has_audio = True
        self._first_markers.setdefault("first_audio_delta_ns", receive_ns)
        delta_gap_ms = self._optional_elapsed_ms(
            self._previous_audio_delta_ns, receive_ns
        )
        if delta_gap_ms is not None:
            self._timing("audio_delta_gap", delta_gap_ms)
        self._previous_audio_delta_ns = receive_ns
        if self._first_audio_delta_session_ns is None:
            self._first_audio_delta_session_ns = receive_ns
        self._last_audio_delta_session_ns = receive_ns
        self._audio_delta_count += 1
        self._provider_delta_bytes += decoded_bytes
        duration_ms = self._elapsed_ms(resample_start_ns, resample_end_ns)
        self._timing("response_resample", duration_ms)
        decoded_audio_ms = self.playback_ms(decoded_bytes, source_rate)
        resampled_audio_ms = self.playback_ms(resampled_bytes, target_rate)
        self._decoded_response_audio_ms += decoded_audio_ms
        self._resampled_response_audio_ms += resampled_audio_ms
        self._timing("audio_delta_duration", resampled_audio_ms)
        self.record(
            "response_audio_delta",
            t_ns=receive_ns,
            response_index=self._response_index,
            first_for_response=first_for_response,
            encoded_chars=encoded_chars,
            decoded_pcm_bytes=decoded_bytes,
            decoded_samples=decoded_bytes // 2,
            decoded_audio_ms=decoded_audio_ms,
            provider_delta_count=self._audio_delta_count,
            provider_delta_bytes=decoded_bytes,
            provider_delta_duration_ms=decoded_audio_ms,
            previous_delta_gap_ms=delta_gap_ms,
            resample_start_ns=resample_start_ns,
            resample_end_ns=resample_end_ns,
            resample_duration_ms=duration_ms,
            resampled_pcm_bytes=resampled_bytes,
            resampled_samples=resampled_bytes // 2,
            resampled_audio_ms=resampled_audio_ms,
        )
        if first_for_response:
            self.record(
                "FIRST_AUDIO_DELTA_RECEIVED",
                t_ns=receive_ns,
                response_index=self._response_index,
            )
        return self._response_index

    @_synchronized
    def record_playback_enqueue(
        self,
        *,
        t_ns: int,
        before_bytes: int,
        after_bytes: int,
        sample_rate: int,
        added_bytes: int | None = None,
    ) -> None:
        before_ms = self.playback_ms(before_bytes, sample_rate)
        after_ms = self.playback_ms(after_bytes, sample_rate)
        accepted_bytes = (
            max(0, after_bytes - before_bytes)
            if added_bytes is None
            else max(0, added_bytes)
        )
        added_ms = self.playback_ms(accepted_bytes, sample_rate)
        self._enqueued_response_audio_ms += added_ms
        self._track_playback_backlog(after_ms, active=True)
        self.record(
            "playback_enqueue",
            t_ns=t_ns,
            response_index=self._response_index,
            before_bytes=before_bytes,
            before_ms=before_ms,
            after_bytes=after_bytes,
            after_ms=after_ms,
            added_bytes=accepted_bytes,
            added_ms=added_ms,
            playback_queue_depth_bytes=after_bytes,
            playback_queue_depth_ms=after_ms,
        )

    @_synchronized
    def record_playback_wait_start(
        self, *, t_ns: int, depth_bytes: int, sample_rate: int
    ) -> None:
        self._playback_wait_start_ns = t_ns
        if self._response_active and self._starvation_start_ns is None:
            self._starvation_start_ns = t_ns
            self.record(
                "PLAYBACK_STARVATION_STARTED",
                t_ns=t_ns,
                response_index=self._response_index,
            )
        self.record(
            "playback_wait_start",
            t_ns=t_ns,
            playback_queue_depth_bytes=depth_bytes,
            playback_queue_depth_ms=self.playback_ms(depth_bytes, sample_rate),
            response_active=self._response_active,
        )

    @_synchronized
    def record_playback_wait_end(
        self, *, t_ns: int, depth_bytes: int, sample_rate: int
    ) -> None:
        wait_start_ns = self._playback_wait_start_ns
        self._playback_wait_start_ns = None
        self._close_starvation(t_ns)
        self.record(
            "playback_wait_end",
            t_ns=t_ns,
            wait_duration_ms=self._optional_elapsed_ms(wait_start_ns, t_ns),
            playback_queue_depth_bytes=depth_bytes,
            playback_queue_depth_ms=self.playback_ms(depth_bytes, sample_rate),
            response_active=self._response_active,
        )

    @_synchronized
    def record_queue_overflow(
        self,
        *,
        channel: str,
        dropped_bytes: int,
        sample_rate: int,
        depth: int,
        capacity: int,
    ) -> None:
        safe_channel = channel if channel in {
            "capture_queue",
            "playback_buffer",
        } else "unknown"
        dropped = max(0, dropped_bytes)
        dropped_ms = self.playback_ms(dropped, sample_rate)
        self._queue_overflow_counts[safe_channel] += 1
        self._queue_dropped_bytes[safe_channel] += dropped
        self._queue_dropped_audio_ms[safe_channel] += dropped_ms
        self.record(
            "audio_queue_overflow",
            channel=safe_channel,
            dropped_bytes=dropped,
            dropped_audio_ms=dropped_ms,
            depth=max(0, depth),
            capacity=max(0, capacity),
        )

    @_synchronized
    def record_stage_timing(
        self, stage: str, *, start_ns: int, end_ns: int
    ) -> None:
        safe_stage = stage if stage in {
            "response_processing",
        } else "worker_other"
        duration_ms = self._elapsed_ms(start_ns, end_ns)
        self._timing(safe_stage, duration_ms)
        self.record(
            "stage_timing",
            t_ns=end_ns,
            stage=safe_stage,
            start_ns=start_ns,
            end_ns=end_ns,
            duration_ms=duration_ms,
        )

    def _track_playback_backlog(self, backlog_ms: float, *, active: bool) -> None:
        self._maximum_playback_backlog_ms = max(self._maximum_playback_backlog_ms, backlog_ms)
        if active:
            current = self._minimum_playback_backlog_active_ms
            self._minimum_playback_backlog_active_ms = backlog_ms if current is None else min(current, backlog_ms)

    @_synchronized
    def record_write(
        self,
        *,
        write_start_ns: int,
        write_end_ns: int,
        buffer_before_bytes: int,
        buffer_after_bytes: int,
        response_audio_frames: int,
        zero_frames: int,
        frames_written: int,
        sample_rate: int,
        underflow: bool,
        response_active: bool,
        preceding_recv_timeout: bool = False,
        preceding_recv_wait_ms: float = 0.0,
    ) -> None:
        duration_ms = self._elapsed_ms(write_start_ns, write_end_ns)
        self._timing("stream_write", duration_ms)
        written_audio_ms = self.playback_ms(response_audio_frames * 2, sample_rate)
        zero_audio_ms = self.playback_ms(zero_frames * 2, sample_rate)
        active_write_gap_ms: float | None = None
        non_silent_write_gap_ms: float | None = None
        non_silent_write_idle_gap_ms: float | None = None
        if underflow:
            self._output_underflow_count += 1
        if response_active:
            self._active_response_write_count += 1
            active_write_gap_ms = self._optional_elapsed_ms(
                self._previous_active_write_start_ns, write_start_ns
            )
            if active_write_gap_ms is not None:
                self._timing("active_response_write_gap", active_write_gap_ms)
            self._previous_active_write_start_ns = write_start_ns
        if response_active and response_audio_frames < frames_written:
            self._insufficient_audio_cycles += 1
        first_non_silent_write = (
            response_audio_frames > 0
            and "first_non_silent_write_ns" not in self._first_markers
        )
        if response_audio_frames > 0:
            self._first_markers.setdefault("first_non_silent_write_ns", write_start_ns)
            self._non_silent_write_count += 1
            self._non_silent_audio_written_ms += written_audio_ms
            non_silent_write_gap_ms = self._optional_elapsed_ms(
                self._previous_non_silent_write_start_ns, write_start_ns
            )
            non_silent_write_idle_gap_ms = self._optional_elapsed_ms(
                self._previous_non_silent_write_end_ns, write_start_ns
            )
            if non_silent_write_gap_ms is not None:
                self._timing("non_silent_write_gap", non_silent_write_gap_ms)
            if non_silent_write_idle_gap_ms is not None:
                self._timing(
                    "non_silent_write_idle_gap", non_silent_write_idle_gap_ms
                )
            self._previous_non_silent_write_start_ns = write_start_ns
            self._previous_non_silent_write_end_ns = write_end_ns
            self._close_starvation(write_start_ns)
        elif response_active:
            self._fully_silent_active_write_count += 1
            if self._starvation_start_ns is None:
                self._starvation_start_ns = write_start_ns
                self.record(
                    "PLAYBACK_STARVATION_STARTED",
                    t_ns=write_start_ns,
                    response_index=self._response_index,
                )
        else:
            self._close_starvation(write_start_ns)
        if response_active and buffer_after_bytes == 0:
            self._playback_buffer_zero_active_count += 1
        if zero_frames > 0 and response_active:
            self._zero_padded_write_count += 1
            self._zero_padding_frames += zero_frames
            if response_audio_frames > 0:
                self._partial_zero_padded_write_count += 1
            if preceding_recv_timeout:
                self._zero_padded_after_recv_timeout_count += 1
        if response_active and response_audio_frames == 0 and preceding_recv_timeout:
            self._starved_after_recv_timeout_count += 1
        after_ms = self.playback_ms(buffer_after_bytes, sample_rate)
        self._track_playback_backlog(after_ms, active=response_active)
        self.record(
            "stream_write",
            t_ns=write_end_ns,
            write_start_ns=write_start_ns,
            write_end_ns=write_end_ns,
            write_duration_ms=duration_ms,
            playback_write_start_ns=write_start_ns,
            playback_write_end_ns=write_end_ns,
            playback_write_duration_ms=duration_ms,
            buffer_before_bytes=buffer_before_bytes,
            buffer_before_ms=self.playback_ms(buffer_before_bytes, sample_rate),
            buffer_after_bytes=buffer_after_bytes,
            buffer_after_ms=after_ms,
            playback_queue_depth_bytes=buffer_after_bytes,
            playback_queue_depth_ms=after_ms,
            bytes_removed=max(0, buffer_before_bytes - buffer_after_bytes),
            response_audio_frames=response_audio_frames,
            response_audio_duration_ms=written_audio_ms,
            zero_frames=zero_frames,
            zero_audio_duration_ms=zero_audio_ms,
            frames_written=frames_written,
            underflow=underflow,
            response_active=response_active,
            preceding_recv_timeout=preceding_recv_timeout,
            preceding_recv_wait_ms=preceding_recv_wait_ms,
            active_response_write_gap_ms=active_write_gap_ms,
            non_silent_write_gap_ms=non_silent_write_gap_ms,
            non_silent_write_idle_gap_ms=non_silent_write_idle_gap_ms,
        )
        if first_non_silent_write:
            self.record(
                "FIRST_NON_SILENT_WRITE",
                t_ns=write_start_ns,
                response_index=self._response_index,
            )
        if (
            self._response_period_start_ns is not None
            and not self._response_active
            and buffer_after_bytes == 0
        ):
            response_period_end_ns = (
                write_end_ns if response_audio_frames > 0 else write_start_ns
            )
            self._close_starvation(response_period_end_ns)
            self._close_response_period(response_period_end_ns)

    @_synchronized
    def record_loop(
        self,
        *,
        loop_start_ns: int,
        loop_end_ns: int,
        read_ms: float,
        input_resample_ms: float,
        send_ms: float,
        recv_ms: float,
        response_processing_ms: float,
        write_ms: float,
    ) -> None:
        total_ms = self._elapsed_ms(loop_start_ns, loop_end_ns)
        known_ms = read_ms + input_resample_ms + send_ms + recv_ms + response_processing_ms + write_ms
        other_ms = max(0.0, total_ms - known_ms)
        stages = {
            "loop_total": total_ms,
            "input_resample": input_resample_ms,
            "loop_other": other_ms,
        }
        if response_processing_ms > 0:
            stages["response_processing"] = response_processing_ms
        for stage, duration_ms in stages.items():
            self._timing(stage, duration_ms)
        self.record(
            "loop_iteration",
            t_ns=loop_end_ns,
            total_iteration_ms=total_ms,
            read_ms=read_ms,
            input_resample_ms=input_resample_ms,
            send_ms=send_ms,
            recv_ms=recv_ms,
            response_processing_ms=response_processing_ms,
            write_ms=write_ms,
            other_ms=other_ms,
        )

    def _stage_summary(self, stage: str) -> dict[str, float | int | None]:
        samples = list(self._timing_samples.get(stage, ()))
        count = self._timing_counts.get(stage, 0)
        if count == 0:
            return {
                "count": 0,
                "mean_ms": None,
                "median_ms": None,
                "p95_ms": None,
                "max_ms": None,
            }
        ordered = sorted(samples)
        p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return {
            "count": count,
            "mean_ms": self._timing_sums[stage] / count,
            "median_ms": statistics.median(samples),
            "p95_ms": ordered[p95_index],
            "max_ms": self._timing_maxima[stage],
            "retained_samples": len(samples),
            "dropped_samples": self._timing_dropped.get(stage, 0),
        }

    def _response_active_wall_ms(self, final_ns: int) -> float:
        active_ns = self._response_period_closed_ns
        if self._response_period_start_ns is not None:
            active_ns += max(0, final_ns - self._response_period_start_ns)
        return active_ns / 1_000_000

    def _starvation_snapshot(self, final_ns: int) -> tuple[int, float, float]:
        count = self._starvation_closed_count
        total_ns = self._starvation_closed_ns
        maximum_ns = self._starvation_max_closed_ns
        if self._starvation_start_ns is not None:
            open_ns = max(0, final_ns - self._starvation_start_ns)
            count += 1
            total_ns += open_ns
            maximum_ns = max(maximum_ns, open_ns)
        return count, total_ns / 1_000_000, maximum_ns / 1_000_000

    @_synchronized
    def summary(self, *, end_ns: int | None = None) -> dict[str, object]:
        final_ns = self._clock_ns() if end_ns is None else end_ns
        captured_audio_ms = self.playback_ms(self._captured_frames * 2, self._capture_rate)
        sent_audio_ms = self.playback_ms(self._sent_frames * 2, self._send_rate)
        capture_wall_ms = self._elapsed_ms(self._first_capture_ns, self._last_capture_ns)
        send_wall_ms = self._elapsed_ms(self._first_send_ns, self._last_send_ns)
        speech_stopped = self._first_markers.get("speech_stopped_ns")
        first_response = self._first_markers.get("first_response_event_ns")
        first_delta = self._first_markers.get("first_audio_delta_ns")
        first_write = self._first_markers.get("first_non_silent_write_ns")
        response_active_wall_ms = self._response_active_wall_ms(final_ns)
        starvation_count, starvation_total_ms, starvation_max_ms = (
            self._starvation_snapshot(final_ns)
        )
        delta_arrival_wall_ms = self._elapsed_ms(
            self._first_audio_delta_session_ns, self._last_audio_delta_session_ns
        )
        non_silent_write_gap = self._stage_summary("non_silent_write_gap")
        active_write_gap = self._stage_summary("active_response_write_gap")
        audio_delta_gap = self._stage_summary("audio_delta_gap")
        block_duration_value = self._metadata.get("block_duration_ms", 0.0)
        block_duration_ms = (
            float(block_duration_value)
            if isinstance(block_duration_value, (int, float))
            else 0.0
        )
        playback_duty_cycle = self._ratio(
            self._non_silent_audio_written_ms, response_active_wall_ms
        )
        stages = (
            "loop_total",
            "stream_read",
            "input_resample",
            "ws_send",
            "ws_recv",
            "response_processing",
            "response_resample",
            "stream_write",
            "loop_other",
            "audio_delta_gap",
            "audio_delta_recv_wait",
            "audio_delta_duration",
            "active_response_write_gap",
            "non_silent_write_gap",
            "non_silent_write_idle_gap",
            "playback_starvation",
        )
        latency_timeline = {
            "speech_started_ns": self._first_markers.get("speech_started_ns"),
            "speech_stopped_ns": speech_stopped,
            "first_response_event_ns": self._first_markers.get(
                "first_response_event_ns"
            ),
            "first_audio_delta_ns": first_delta,
            "first_non_silent_write_ns": first_write,
            "speech_stopped_to_first_audio_delta_ms": self._optional_elapsed_ms(
                speech_stopped, first_delta
            ),
            "speech_stopped_to_first_response_event_ms": (
                self._optional_elapsed_ms(speech_stopped, first_response)
            ),
            "first_response_event_to_first_audio_delta_ms": (
                self._optional_elapsed_ms(first_response, first_delta)
            ),
            "first_audio_delta_to_first_non_silent_write_ms": (
                self._optional_elapsed_ms(first_delta, first_write)
            ),
            "speech_stopped_to_first_non_silent_write_ms": (
                self._optional_elapsed_ms(speech_stopped, first_write)
            ),
        }
        playback_timeline = {
            "audio_delta_count": self._audio_delta_count,
            "provider_delta_count": self._audio_delta_count,
            "provider_delta_bytes": self._provider_delta_bytes,
            "provider_delta_duration_ms": self._decoded_response_audio_ms,
            "audio_delta_gap_ms": audio_delta_gap,
            "audio_delta_recv_wait_ms": self._stage_summary(
                "audio_delta_recv_wait"
            ),
            "maximum_consecutive_audio_delta_events": (
                self._maximum_consecutive_audio_delta_events
            ),
            "near_zero_wait_audio_delta_count": (
                self._near_zero_wait_audio_delta_count
            ),
            "resampled_response_audio_ms": self._resampled_response_audio_ms,
            "response_audio_arrival_realtime_ratio": self._ratio(
                self._resampled_response_audio_ms, delta_arrival_wall_ms
            ),
            "enqueued_response_audio_ms": self._enqueued_response_audio_ms,
            "non_silent_audio_written_ms": self._non_silent_audio_written_ms,
            "enqueued_minus_written_audio_ms": (
                self._enqueued_response_audio_ms
                - self._non_silent_audio_written_ms
            ),
            "active_response_wall_ms": response_active_wall_ms,
            "PLAYBACK_DUTY_CYCLE": playback_duty_cycle,
            "active_response_write_count": self._active_response_write_count,
            "active_response_write_gap_ms": active_write_gap,
            "non_silent_write_count": self._non_silent_write_count,
            "NON_SILENT_WRITE_GAP_MS": non_silent_write_gap,
            "non_silent_write_idle_gap_ms": self._stage_summary(
                "non_silent_write_idle_gap"
            ),
            "maximum_playback_backlog_ms": self._maximum_playback_backlog_ms,
            "minimum_playback_backlog_active_ms": (
                self._minimum_playback_backlog_active_ms
            ),
            "playback_backlog_exceeded_one_block": (
                self._maximum_playback_backlog_ms > block_duration_ms
                if block_duration_ms > 0
                else None
            ),
            "playback_buffer_zero_while_active_count": (
                self._playback_buffer_zero_active_count
            ),
            "playback_starvation_period_count": starvation_count,
            "playback_starvation_total_ms": starvation_total_ms,
            "playback_starvation_max_ms": starvation_max_ms,
            "zero_padded_write_count": self._zero_padded_write_count,
            "artificial_zero_padding_count": self._zero_padded_write_count,
            "partial_zero_padded_write_count": (
                self._partial_zero_padded_write_count
            ),
            "fully_silent_active_write_count": (
                self._fully_silent_active_write_count
            ),
            "zero_padded_after_recv_timeout_count": (
                self._zero_padded_after_recv_timeout_count
            ),
            "starved_after_recv_timeout_count": (
                self._starved_after_recv_timeout_count
            ),
            "total_inserted_silence_ms": self.playback_ms(
                self._zero_padding_frames * 2, self._duplex_rate
            ),
            "output_underflow_count": self._output_underflow_count,
            "playback_buffer_overflow_count": self._queue_overflow_counts.get(
                "playback_buffer", 0
            ),
            "playback_buffer_dropped_audio_ms": (
                self._queue_dropped_audio_ms.get("playback_buffer", 0.0)
            ),
            "response_audio_done_ns": self._first_markers.get(
                "response_audio_done_ns"
            ),
            "response_done_ns": self._first_markers.get("response_done_ns"),
        }
        return {
            "session_id": self.session_id,
            "session_duration_ms": self._elapsed_ms(self.start_ns, final_ns),
            "captured_audio_ms": captured_audio_ms,
            "sent_audio_ms": sent_audio_ms,
            "capture_realtime_ratio": self._ratio(captured_audio_ms, capture_wall_ms),
            "send_realtime_ratio": self._ratio(sent_audio_ms, send_wall_ms),
            "input_overflow_count": self._input_overflow_count,
            "output_underflow_count": self._output_underflow_count,
            "recv_call_count": self._recv_call_count,
            "recv_timeout_count": self._recv_timeout_count,
            "recv_average_wait_ms": (
                None
                if self._recv_call_count == 0
                else self._timing_sums["ws_recv"] / self._recv_call_count
            ),
            "recv_max_wait_ms": self._timing_maxima.get("ws_recv") or None,
            "capture_queue_overflow_count": self._queue_overflow_counts.get(
                "capture_queue", 0
            ),
            "capture_queue_dropped_audio_ms": self._queue_dropped_audio_ms.get(
                "capture_queue", 0.0
            ),
            "playback_buffer_overflow_count": self._queue_overflow_counts.get(
                "playback_buffer", 0
            ),
            "playback_buffer_dropped_audio_ms": (
                self._queue_dropped_audio_ms.get("playback_buffer", 0.0)
            ),
            "queue_overflow_counts": dict(self._queue_overflow_counts),
            "queue_dropped_bytes": dict(self._queue_dropped_bytes),
            "queue_dropped_audio_ms": dict(self._queue_dropped_audio_ms),
            "audio_devices": self._metadata.get("audio_devices", {}),
            "input_level_forensics": {
                "capture_block_count": self._input_level_blocks,
                "silence_peak_threshold": EFFECTIVE_SILENCE_PEAK,
                "effectively_silent_block_count": self._input_silent_blocks,
                "effectively_silent_block_ratio": (
                    None
                    if self._input_level_blocks == 0
                    else self._input_silent_blocks / self._input_level_blocks
                ),
                "average_rms": (
                    None
                    if self._input_level_blocks == 0
                    else self._input_rms_sum / self._input_level_blocks
                ),
                "maximum_rms": self._input_rms_max,
                "maximum_peak": self._input_peak_max,
            },
            **self._first_markers,
            "speech_stopped_to_first_audio_delta_ms": self._optional_elapsed_ms(
                speech_stopped, first_delta
            ),
            "speech_stopped_to_first_response_event_ms": (
                self._optional_elapsed_ms(speech_stopped, first_response)
            ),
            "first_response_event_to_first_audio_delta_ms": (
                self._optional_elapsed_ms(first_response, first_delta)
            ),
            "first_audio_delta_to_first_non_silent_write_ms": self._optional_elapsed_ms(
                first_delta, first_write
            ),
            "speech_stopped_to_first_non_silent_write_ms": (
                self._optional_elapsed_ms(speech_stopped, first_write)
            ),
            "audio_delta_count": self._audio_delta_count,
            "provider_delta_count": self._audio_delta_count,
            "provider_delta_bytes": self._provider_delta_bytes,
            "provider_delta_duration_ms": self._decoded_response_audio_ms,
            "audio_delta_gap_ms": audio_delta_gap,
            "maximum_consecutive_audio_delta_events": (
                self._maximum_consecutive_audio_delta_events
            ),
            "near_zero_wait_audio_delta_count": (
                self._near_zero_wait_audio_delta_count
            ),
            "response_active_wall_ms": response_active_wall_ms,
            "non_silent_audio_written_ms": self._non_silent_audio_written_ms,
            "PLAYBACK_DUTY_CYCLE": playback_duty_cycle,
            "NON_SILENT_WRITE_GAP_MS": non_silent_write_gap,
            "maximum_playback_backlog_ms": self._maximum_playback_backlog_ms,
            "minimum_playback_backlog_active_ms": self._minimum_playback_backlog_active_ms,
            "playback_buffer_zero_while_active_count": (
                self._playback_buffer_zero_active_count
            ),
            "playback_starvation_period_count": starvation_count,
            "playback_starvation_total_ms": starvation_total_ms,
            "playback_starvation_max_ms": starvation_max_ms,
            "insufficient_audio_cycle_count": self._insufficient_audio_cycles,
            "zero_padded_write_count": self._zero_padded_write_count,
            "artificial_zero_padding_count": self._zero_padded_write_count,
            "partial_zero_padded_write_count": (
                self._partial_zero_padded_write_count
            ),
            "fully_silent_active_write_count": (
                self._fully_silent_active_write_count
            ),
            "zero_padded_after_recv_timeout_count": (
                self._zero_padded_after_recv_timeout_count
            ),
            "starved_after_recv_timeout_count": (
                self._starved_after_recv_timeout_count
            ),
            "total_inserted_silence_ms": self.playback_ms(
                self._zero_padding_frames * 2, self._duplex_rate
            ),
            "latency_timeline": latency_timeline,
            "playback_timeline": playback_timeline,
            "event_count_retained": len(self._events),
            "event_count_dropped": self._dropped_events,
            "websocket_lifecycle": self.websocket_forensics(),
            "timings": {stage: self._stage_summary(stage) for stage in stages},
        }

    @_synchronized
    def finish(self, *, end_ns: int | None = None) -> tuple[Path, Path] | None:
        final_ns = self._clock_ns() if end_ns is None else end_ns
        self._close_starvation(final_ns)
        self._close_response_period(final_ns)
        self.record("session_end", t_ns=final_ns)
        summary = self.summary(end_ns=final_ns)
        stamp = self.start_utc.strftime("%Y%m%d-%H%M%S-%f")
        stem = f"qwen-live-diag-{stamp}-{self.session_id}"
        jsonl_path = self.output_dir / f"{stem}.jsonl"
        summary_path = self.output_dir / f"{stem}.summary.txt"
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with jsonl_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        {"kind": "session_metadata", **self._metadata},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                for event in self._events:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                websocket_forensics = self.websocket_forensics()
                if websocket_forensics["recent_events"]:
                    handle.write(
                        json.dumps(
                            {
                                "kind": "websocket_forensics",
                                **websocket_forensics,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                handle.write(
                    json.dumps(
                        {"kind": "session_summary", **summary}, ensure_ascii=False
                    )
                    + "\n"
                )
            with summary_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(self._human_summary(summary))
        except OSError:
            return None
        return jsonl_path, summary_path

    @staticmethod
    def _human_summary(summary: dict[str, object]) -> str:
        keys = (
            "session_id",
            "session_duration_ms",
            "captured_audio_ms",
            "sent_audio_ms",
            "capture_realtime_ratio",
            "send_realtime_ratio",
            "input_overflow_count",
            "output_underflow_count",
            "recv_call_count",
            "recv_timeout_count",
            "recv_average_wait_ms",
            "recv_max_wait_ms",
            "capture_queue_overflow_count",
            "capture_queue_dropped_audio_ms",
            "playback_buffer_overflow_count",
            "playback_buffer_dropped_audio_ms",
            "speech_started_ns",
            "speech_stopped_ns",
            "first_response_event_ns",
            "first_audio_delta_ns",
            "first_non_silent_write_ns",
            "speech_stopped_to_first_audio_delta_ms",
            "speech_stopped_to_first_response_event_ms",
            "first_response_event_to_first_audio_delta_ms",
            "first_audio_delta_to_first_non_silent_write_ms",
            "speech_stopped_to_first_non_silent_write_ms",
            "audio_delta_count",
            "maximum_consecutive_audio_delta_events",
            "near_zero_wait_audio_delta_count",
            "response_active_wall_ms",
            "non_silent_audio_written_ms",
            "PLAYBACK_DUTY_CYCLE",
            "NON_SILENT_WRITE_GAP_MS",
            "maximum_playback_backlog_ms",
            "minimum_playback_backlog_active_ms",
            "playback_buffer_zero_while_active_count",
            "playback_starvation_period_count",
            "playback_starvation_total_ms",
            "playback_starvation_max_ms",
            "insufficient_audio_cycle_count",
            "zero_padded_write_count",
            "partial_zero_padded_write_count",
            "fully_silent_active_write_count",
            "zero_padded_after_recv_timeout_count",
            "starved_after_recv_timeout_count",
            "total_inserted_silence_ms",
            "event_count_retained",
            "event_count_dropped",
        )
        lines = ["ORION Qwen Live diagnostic summary"]
        lines.extend(f"{key}: {summary.get(key)}" for key in keys)
        for heading, key in (
            ("LATENCY TIMELINE", "latency_timeline"),
            ("PLAYBACK TIMELINE", "playback_timeline"),
            ("WEBSOCKET LIFECYCLE", "websocket_lifecycle"),
        ):
            lines.append(f"{heading}:")
            timeline = summary.get(key)
            if isinstance(timeline, dict):
                lines.extend(
                    f"  {name}: {value}" for name, value in timeline.items()
                )
        lines.append("timings:")
        timings = summary.get("timings")
        if isinstance(timings, dict):
            for stage, values in timings.items():
                lines.append(f"  {stage}: {values}")
        return "\n".join(lines) + "\n"
