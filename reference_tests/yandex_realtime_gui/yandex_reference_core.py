"""Standalone Yandex Realtime transport and diagnostics.

This module intentionally imports no ORION package.  It is the provider reference
path for the standalone YandexRealtimeTester application only.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import platform
import queue
import re
import sys
import threading
import time
from array import array
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import quote

import aiohttp
import sounddevice as sd

from yandex_audio_correlation import CorrelationProbe

APP_NAME = "Yandex Realtime Reference Tester"
APP_VERSION = "1.1A"
ENDPOINT = "wss://ai.api.cloud.yandex.net/v1/realtime"
DEFAULT_MODEL = "speech-realtime-260528"
DEFAULT_VOICE = "dasha"
DEFAULT_LANGUAGE = "ru-RU"
DEFAULT_INSTRUCTIONS = (
    "You are a conversational voice assistant. "
    "Respond naturally and concisely in Russian."
)

# Current official Yandex voice-agent examples declare mono headerless LPCM at
# 44.1 kHz. SpeechKit's LPCM definition is signed 16-bit little-endian.
INPUT_RATE = 44_100
OUTPUT_RATE = 44_100
CHANNELS = 1
SAMPLE_BYTES = 2
DTYPE = "int16"
BLOCK_MS = 20
INPUT_FRAMES = INPUT_RATE * BLOCK_MS // 1000
PLAYBACK_SLICE_MS = 20
PLAYBACK_SLICE_FRAMES = OUTPUT_RATE * PLAYBACK_SLICE_MS // 1000
PLAYBACK_SLICE_BYTES = PLAYBACK_SLICE_FRAMES * CHANNELS * SAMPLE_BYTES
VAD_THRESHOLD = 0.5
VAD_SILENCE_MS = 400
SILENT_RMS_THRESHOLD = 50.0

EventCallback = Callable[[str, dict[str, object]], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def dependency_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "not installed"


def safe_folder_id(folder_id: str) -> str:
    value = folder_id.strip()
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


_AUTH_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)([^\s,;]+(?:\s+[^\s,;]+)?)"),
    re.compile(r"(?i)\b(api-key|bearer)\s+[^\s,;]+"),
    re.compile(r"(?i)([?&](?:api[_-]?key|token)=)[^&\s]+"),
)


def sanitize_text(value: object, api_key: str = "") -> str:
    text = str(value)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = _AUTH_PATTERNS[0].sub("[REDACTED]", text)
    text = _AUTH_PATTERNS[1].sub(r"\1 [REDACTED]", text)
    text = _AUTH_PATTERNS[2].sub(r"\1[REDACTED]", text)
    return text


def sanitize_value(value: object, api_key: str = "") -> object:
    if isinstance(value, dict):
        safe: dict[str, object] = {}
        for key, item in value.items():
            if key.casefold() in {"authorization", "api_key", "apikey", "iam_token", "token"}:
                safe[str(key)] = "[REDACTED]"
            else:
                safe[str(key)] = sanitize_value(item, api_key)
        return safe
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item, api_key) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, api_key)
    return value


@dataclass(frozen=True, slots=True)
class AudioDevice:
    index: int
    name: str
    hostapi_index: int
    hostapi_name: str
    default_samplerate: float
    max_input_channels: int
    max_output_channels: int

    @property
    def label(self) -> str:
        return f"{self.index} — {self.name} — {self.hostapi_name}"

    def identity(self) -> tuple[int, str, int, str]:
        return self.index, self.name, self.hostapi_index, self.hostapi_name


def list_audio_devices(audio_backend: Any = sd) -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Enumerate every PortAudio endpoint without forcing/filtering a host API."""

    hostapis = list(audio_backend.query_hostapis())
    inputs: list[AudioDevice] = []
    outputs: list[AudioDevice] = []
    for index, raw in enumerate(audio_backend.query_devices()):
        hostapi_index = int(raw["hostapi"])
        hostapi_name = str(hostapis[hostapi_index]["name"])
        device = AudioDevice(
            index=index,
            name=str(raw["name"]),
            hostapi_index=hostapi_index,
            hostapi_name=hostapi_name,
            default_samplerate=float(raw["default_samplerate"]),
            max_input_channels=int(raw["max_input_channels"]),
            max_output_channels=int(raw["max_output_channels"]),
        )
        if device.max_input_channels >= 1:
            inputs.append(device)
        if device.max_output_channels >= 1:
            outputs.append(device)
    return inputs, outputs


def find_exact_device(
    selected: AudioDevice,
    devices: list[AudioDevice],
    direction: str,
) -> AudioDevice:
    for current in devices:
        if current.identity() == selected.identity():
            return current
    raise ValueError(
        f"{direction} device selection is stale: PortAudio index {selected.index} "
        f"({selected.name} — {selected.hostapi_name}). Refresh and reselect it."
    )


def validate_audio_format(config: "SessionConfig", audio_backend: Any = sd) -> None:
    inputs, outputs = list_audio_devices(audio_backend)
    find_exact_device(config.input_device, inputs, "Input")
    find_exact_device(config.output_device, outputs, "Output")
    try:
        audio_backend.check_input_settings(
            device=config.input_device.index,
            channels=CHANNELS,
            dtype=DTYPE,
            samplerate=INPUT_RATE,
        )
    except Exception as exc:
        raise UnsupportedAudioFormat(
            f"Input endpoint {config.input_device.index} ({config.input_device.name}, "
            f"{config.input_device.hostapi_name}) does not accept mono PCM16 at {INPUT_RATE} Hz: {exc}"
        ) from exc
    try:
        audio_backend.check_output_settings(
            device=config.output_device.index,
            channels=CHANNELS,
            dtype=DTYPE,
            samplerate=OUTPUT_RATE,
        )
    except Exception as exc:
        raise UnsupportedAudioFormat(
            f"Output endpoint {config.output_device.index} ({config.output_device.name}, "
            f"{config.output_device.hostapi_name}) does not accept mono PCM16 at {OUTPUT_RATE} Hz: {exc}"
        ) from exc


class UnsupportedAudioFormat(RuntimeError):
    pass


def build_model_uri(folder_id: str, model: str) -> str:
    folder = folder_id.strip()
    model_name = model.strip()
    if not folder:
        raise ValueError("Folder ID is required.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", folder):
        raise ValueError("Folder ID contains unsupported characters.")
    if not model_name:
        raise ValueError("Model is required.")
    if model_name.startswith("gpt://"):
        raise ValueError("Enter the model name only; Folder ID is configured separately.")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", model_name):
        raise ValueError("Model contains unsupported characters.")
    return f"gpt://{folder}/{model_name}"


def build_url(folder_id: str, model: str) -> str:
    model_uri = build_model_uri(folder_id, model)
    return f"{ENDPOINT}?model={quote(model_uri, safe=':/-_.')}"


def build_session_update(config: "SessionConfig") -> dict[str, object]:
    return {
        "type": "session.update",
        "session": {
            "instructions": config.instructions,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": INPUT_RATE},
                    "languages": [config.language],
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": VAD_THRESHOLD,
                        "silence_duration_ms": VAD_SILENCE_MS,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": OUTPUT_RATE},
                    "voice": config.voice,
                },
            },
        },
    }


def encode_input_audio_event(pcm: bytes) -> dict[str, object]:
    return {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(pcm).decode("ascii"),
    }


def decode_output_audio(event: dict[str, Any]) -> bytes:
    delta = event.get("delta")
    if not isinstance(delta, str):
        raise ValueError("response.output_audio.delta is missing string field 'delta'.")
    return base64.b64decode(delta, validate=True)


def audio_duration_ms(byte_count: int, rate: int = OUTPUT_RATE) -> float:
    return round(byte_count / (rate * CHANNELS * SAMPLE_BYTES) * 1000, 2)


def split_playback_pcm(pcm: bytes) -> tuple[bytes, ...]:
    """Split provider PCM into exact frame-aligned playback slices."""

    if len(pcm) % (CHANNELS * SAMPLE_BYTES):
        raise ValueError("Provider output PCM is not aligned to complete int16 frames.")
    return tuple(
        pcm[offset : offset + PLAYBACK_SLICE_BYTES]
        for offset in range(0, len(pcm), PLAYBACK_SLICE_BYTES)
    )


@dataclass(slots=True)
class SessionConfig:
    api_key: str
    folder_id: str
    model: str
    voice: str
    language: str
    input_device: AudioDevice
    output_device: AudioDevice
    instructions: str = DEFAULT_INSTRUCTIONS

    def validate(self) -> None:
        if not self.api_key.strip():
            raise ValueError("API key is required.")
        build_model_uri(self.folder_id, self.model)
        if not self.voice.strip():
            raise ValueError("Voice is required.")
        if not self.language.strip():
            raise ValueError("Language is required.")


@dataclass(slots=True)
class ResponseMetric:
    response_id: str
    created_monotonic: float
    first_audio_latency_ms: float | None = None
    latency_basis: str | None = None
    delta_count: int = 0
    decoded_bytes: int = 0
    delta_gaps_ms: list[float] = field(default_factory=list)
    previous_delta_monotonic: float | None = None
    status: str | None = None
    response_completed: bool = False

    def add_audio(self, byte_count: int, now: float, speech_stopped_at: float | None) -> None:
        if self.delta_count == 0:
            if speech_stopped_at is not None:
                self.first_audio_latency_ms = (now - speech_stopped_at) * 1000
                self.latency_basis = "input_audio_buffer.speech_stopped -> first output audio delta"
            else:
                self.first_audio_latency_ms = (now - self.created_monotonic) * 1000
                self.latency_basis = "response.created -> first output audio delta (speech_stopped unavailable)"
        if self.previous_delta_monotonic is not None:
            self.delta_gaps_ms.append((now - self.previous_delta_monotonic) * 1000)
        self.previous_delta_monotonic = now
        self.delta_count += 1
        self.decoded_bytes += byte_count

    def summary(self) -> dict[str, object]:
        return {
            "response_id": self.response_id,
            "first_audio_latency_ms": round(self.first_audio_latency_ms, 2)
            if self.first_audio_latency_ms is not None
            else None,
            "latency_basis": self.latency_basis,
            "delta_count": self.delta_count,
            "decoded_bytes": self.decoded_bytes,
            "total_audio_duration_ms": audio_duration_ms(self.decoded_bytes),
            "max_delta_gap_ms": round(max(self.delta_gaps_ms), 2) if self.delta_gaps_ms else None,
            "average_delta_gap_ms": (
                round(sum(self.delta_gaps_ms) / len(self.delta_gaps_ms), 2)
                if self.delta_gaps_ms
                else None
            ),
            "status": self.status,
            "response_completed": self.response_completed,
        }


@dataclass(frozen=True, slots=True)
class TransportMessage:
    event: dict[str, Any] | None = None
    close_code: int | None = None
    close_reason: str = ""


class RealtimeTransport(Protocol):
    close_code: int | None
    close_reason: str

    async def connect(self, url: str, headers: dict[str, str]) -> None: ...

    async def send_json(self, event: dict[str, object]) -> None: ...

    async def receive(self) -> TransportMessage: ...

    async def close(self) -> None: ...


class AiohttpTransport:
    def __init__(self) -> None:
        self.session: aiohttp.ClientSession | None = None
        self.websocket: aiohttp.ClientWebSocketResponse | None = None
        self.close_code: int | None = None
        self.close_reason = ""

    async def connect(self, url: str, headers: dict[str, str]) -> None:
        session = aiohttp.ClientSession(headers=headers)
        self.session = session
        try:
            self.websocket = await session.ws_connect(url, heartbeat=20, autoclose=True)
        except Exception:
            await session.close()
            self.session = None
            raise

    async def send_json(self, event: dict[str, object]) -> None:
        if self.websocket is None or self.websocket.closed:
            raise ConnectionError("WebSocket is not connected.")
        await self.websocket.send_json(event)

    async def receive(self) -> TransportMessage:
        if self.websocket is None:
            raise ConnectionError("WebSocket is not connected.")
        message = await self.websocket.receive()
        if message.type is aiohttp.WSMsgType.TEXT:
            return TransportMessage(event=json.loads(message.data))
        if message.type is aiohttp.WSMsgType.ERROR:
            error = self.websocket.exception()
            raise error if error is not None else ConnectionError("WebSocket transport error.")
        if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING}:
            self.close_code = self.websocket.close_code
            self.close_reason = str(message.extra or "")
            return TransportMessage(close_code=self.close_code, close_reason=self.close_reason)
        return TransportMessage()

    async def close(self) -> None:
        if self.websocket is not None and not self.websocket.closed:
            await self.websocket.close()
        if self.websocket is not None:
            self.close_code = self.websocket.close_code
        if self.session is not None and not self.session.closed:
            await self.session.close()


@dataclass(frozen=True, slots=True)
class PlaybackSlice:
    response_id: str
    epoch: int
    sequence: int
    pcm: bytes


@dataclass(slots=True)
class ResponsePlaybackState:
    response_id: str
    epoch: int | None
    provider_audio_bytes: int = 0
    slices_created: int = 0
    slices_written: int = 0
    slices_removed: int = 0
    removed_bytes: int = 0
    slices_discarded_stale: int = 0
    stale_bytes: int = 0
    playback_invalidated: bool = False
    provider_response_status: str | None = None
    provider_done: bool = False

    @property
    def terminal_slices(self) -> int:
        return self.slices_written + self.slices_removed + self.slices_discarded_stale

    @property
    def outstanding_slices(self) -> int:
        return max(0, self.slices_created - self.terminal_slices)

    def local_completion_state(self, current: PlaybackSlice | None) -> str:
        is_current = current is not None and current.response_id == self.response_id
        if is_current and self.playback_invalidated:
            return "invalidated_current_write_finishing"
        if is_current:
            return "playing"
        if self.outstanding_slices:
            return "invalidated_pending_discard" if self.playback_invalidated else "queued"
        if self.playback_invalidated:
            return "invalidated"
        if self.provider_done and self.slices_created == 0:
            return "provider_completed_no_audio"
        if self.provider_done:
            return "fully_submitted"
        return "receiving_audio" if self.slices_created else "created"

    def summary(self, current: PlaybackSlice | None) -> dict[str, object]:
        return {
            "response_id": self.response_id,
            "playback_epoch": self.epoch,
            "provider_audio_bytes": self.provider_audio_bytes,
            "slices_created": self.slices_created,
            "slices_written": self.slices_written,
            "slices_removed": self.slices_removed,
            "slices_discarded_stale": self.slices_discarded_stale,
            "playback_invalidated": self.playback_invalidated,
            "provider_response_status": self.provider_response_status,
            "local_playback_completion_state": self.local_completion_state(current),
        }


class YandexReferenceSession:
    """One minimal Yandex WebSocket/audio session, independent of ORION."""

    def __init__(
        self,
        config: SessionConfig,
        callback: EventCallback,
        *,
        audio_backend: Any = sd,
        transport_factory: Callable[[], RealtimeTransport] = AiohttpTransport,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        config.validate()
        self.config = config
        self.callback = callback
        self.audio_backend = audio_backend
        self.transport_factory = transport_factory
        self.clock = clock
        self.stop_event = threading.Event()
        self.session_ready = threading.Event()
        self.playback_queue: queue.Queue[PlaybackSlice | object] = queue.Queue(maxsize=0)
        self._playback_sentinel = object()
        self.thread: threading.Thread | None = None
        self.capture_thread: threading.Thread | None = None
        self.playback_thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.transport: RealtimeTransport | None = None
        self._lock = threading.RLock()
        self.started_at: str | None = None
        self.stopped_at: str | None = None
        self.connect_time_ms: float | None = None
        self.connected_at: str | None = None
        self.session_created_at: str | None = None
        self.session_updated_at: str | None = None
        self.close_time: str | None = None
        self.websocket_close: dict[str, object] = {
            "state": "not closed",
            "code": None,
            "reason": "",
            "clean": None,
        }
        self.session_id: str | None = None
        self.timeline: list[dict[str, object]] = []
        self.server_errors: list[str] = []
        self.transport_errors: list[str] = []
        self.responses: dict[str, ResponseMetric] = {}
        self.latest_response_id: str | None = None
        self.response_count = 0
        self.last_speech_stopped: float | None = None
        self.speech_started_count = 0
        self.speech_stopped_count = 0
        self.transcription_count = 0
        self.transcription_failures = 0
        self.captured_blocks = 0
        self.captured_bytes = 0
        self.input_sample_count = 0
        self.input_square_sum = 0.0
        self.input_peak = 0
        self.silent_blocks = 0
        self.playback_writes = 0
        self.playback_bytes = 0
        self.playback_interruption_count = 0
        self.playback_epoch = 0
        self.active_playback_response_id: str | None = None
        self.response_playback: dict[str, ResponsePlaybackState] = {}
        self.total_slices_created = 0
        self.total_slices_written = 0
        self.short_final_slices = 0
        self.max_slice_bytes = 0
        self.speech_started_seen_count = 0
        self.playback_invalidation_request_count = 0
        self.active_response_invalidation_count = 0
        self.queued_slices_removed_count = 0
        self.queued_bytes_removed = 0
        self.stale_slices_discarded_count = 0
        self.stale_bytes_discarded = 0
        self.current_write_active_at_interrupt_count = 0
        self.current_write_completed_after_interrupt_count = 0
        self.max_current_write_duration_ms = 0.0
        self.application_stop_latency_estimate_ms: float | None = None
        self.current_write_response_id: str | None = None
        self.current_write_epoch: int | None = None
        self.current_write_sequence: int | None = None
        self.current_write_bytes = 0
        self.current_write_started_at: str | None = None
        self.current_write_completed_at: str | None = None
        self.current_write_completed_after_interrupt = False
        self._current_write: PlaybackSlice | None = None
        self._current_write_started_monotonic: float | None = None
        self._current_write_interrupted_at: float | None = None
        self.correlation_probe = CorrelationProbe(clock=clock)
        self._error_seen = False

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        if self.thread is not None:
            raise RuntimeError("A session object cannot be restarted; create a new session.")
        self.started_at = utc_now()
        self.correlation_probe.start()
        self.thread = threading.Thread(
            target=self._thread_main,
            name="yandex-reference-network",
            daemon=True,
        )
        self.thread.start()

    def stop(self, wait: bool = False, timeout: float = 3.0) -> None:
        self.stop_event.set()
        self.session_ready.set()
        self.playback_queue.put(self._playback_sentinel)
        loop = self.loop
        transport = self.transport
        if loop is not None and transport is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(transport.close(), loop)
        if wait and self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout)
        if self.thread is None:
            self.correlation_probe.close()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # asyncio bootstrap guard
            self._terminal_error("WEBSOCKET ERROR", exc)

    async def _run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._status("Validating audio")
        close_code: int | None = None
        close_reason = ""
        clean: bool | None = None
        try:
            validate_audio_format(self.config, self.audio_backend)
            if self.stop_event.is_set():
                return
            self._status("Connecting")
            self.transport = self.transport_factory()
            started = self.clock()
            await self.transport.connect(
                build_url(self.config.folder_id, self.config.model),
                {"Authorization": f"Api-Key {self.config.api_key}"},
            )
            self.connect_time_ms = round((self.clock() - started) * 1000, 2)
            self.connected_at = utc_now()
            self._emit("websocket.connected", connect_time_ms=self.connect_time_ms)
            await self.transport.send_json(build_session_update(self.config))
            self._emit("session.update.sent")
            self.capture_thread = threading.Thread(
                target=self._capture,
                name="yandex-reference-capture",
                daemon=True,
            )
            self.playback_thread = threading.Thread(
                target=self._playback,
                name="yandex-reference-playback",
                daemon=True,
            )
            self.capture_thread.start()
            self.playback_thread.start()

            while not self.stop_event.is_set():
                try:
                    message = await asyncio.wait_for(self.transport.receive(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                if message.event is not None:
                    self.handle_event(message.event)
                if message.close_code is not None or (
                    message.event is None and message.close_reason
                ):
                    close_code = message.close_code
                    close_reason = message.close_reason
                    clean = close_code == 1000 if close_code is not None else None
                    break
        except UnsupportedAudioFormat as exc:
            self._terminal_error("UNSUPPORTED AUDIO FORMAT", exc)
        except ValueError as exc:
            self._terminal_error("SESSION CONFIG ERROR", exc)
        except aiohttp.WSServerHandshakeError as exc:
            category = "AUTH ERROR" if exc.status in {401, 403} else "FOLDER/MODEL ERROR" if exc.status == 400 else "WEBSOCKET ERROR"
            self._terminal_error(category, exc)
        except Exception as exc:
            category = self._classify_exception(exc)
            self._terminal_error(category, exc)
        finally:
            self.stop_event.set()
            self.session_ready.set()
            self.playback_queue.put(self._playback_sentinel)
            if self.transport is not None:
                try:
                    await self.transport.close()
                except Exception as exc:
                    self.transport_errors.append(sanitize_text(exc, self.config.api_key))
                close_code = close_code if close_code is not None else self.transport.close_code
                close_reason = close_reason or self.transport.close_reason
            for worker in (self.capture_thread, self.playback_thread):
                if worker is not None and worker.is_alive():
                    await asyncio.to_thread(worker.join, 1.5)
            self.correlation_probe.close()
            self.stopped_at = utc_now()
            self.close_time = self.stopped_at
            if clean is None and close_code is not None:
                clean = close_code == 1000
            if close_code is not None:
                state = "clean" if clean else "unclean"
            elif self._error_seen:
                state = "error / close code unavailable"
            else:
                state = "closed / close code unavailable"
            self.websocket_close = {
                "state": state,
                "code": close_code,
                "reason": sanitize_text(close_reason or "", self.config.api_key),
                "clean": clean,
            }
            self._emit("websocket.closed", **self.websocket_close)
            if not self._error_seen:
                self._status("Disconnected")
            self.loop = None

    def _classify_exception(self, exc: Exception) -> str:
        text = str(exc).casefold()
        if "input" in text and "device" in text:
            return "INPUT DEVICE ERROR"
        if "output" in text and "device" in text:
            return "OUTPUT DEVICE ERROR"
        if "session" in text or "configuration" in text:
            return "SESSION CONFIG ERROR"
        return "WEBSOCKET ERROR"

    def _terminal_error(self, category: str, exc: Exception) -> None:
        message = sanitize_text(exc, self.config.api_key)
        self._error_seen = True
        if category == "SERVER ERROR":
            self.server_errors.append(message)
        else:
            self.transport_errors.append(message)
        self._emit("client.error", category=category, message=message, exception=type(exc).__name__)
        self._status(category)
        self.stop_event.set()
        self.session_ready.set()
        self.playback_queue.put(self._playback_sentinel)

    def _status(self, value: str) -> None:
        self.callback("status", {"value": value})

    def _emit(self, event: str, **fields: object) -> None:
        safe_fields = sanitize_value(fields, self.config.api_key)
        assert isinstance(safe_fields, dict)
        record = {"timestamp": utc_now(), "event": event, **safe_fields}
        with self._lock:
            self.timeline.append(record)
        self.callback(event, safe_fields)

    def _capture(self) -> None:
        while not self.stop_event.is_set() and not self.session_ready.wait(0.05):
            pass
        if self.stop_event.is_set():
            return
        try:
            with self.audio_backend.RawInputStream(
                samplerate=INPUT_RATE,
                blocksize=INPUT_FRAMES,
                device=self.config.input_device.index,
                channels=CHANNELS,
                dtype=DTYPE,
            ) as stream:
                self._emit(
                    "audio.input.opened",
                    device_index=self.config.input_device.index,
                    rate=INPUT_RATE,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    block_frames=INPUT_FRAMES,
                )
                while not self.stop_event.is_set():
                    pcm_buffer, overflowed = stream.read(INPUT_FRAMES)
                    capture_timestamp = self.clock()
                    pcm = bytes(pcm_buffer)
                    self._record_input_signal(pcm)
                    if overflowed:
                        self._emit("audio.input_overflow")
                    loop = self.loop
                    transport = self.transport
                    if loop is None or transport is None or not loop.is_running():
                        return
                    future = asyncio.run_coroutine_threadsafe(
                        transport.send_json(encode_input_audio_event(pcm)), loop
                    )
                    self.correlation_probe.submit_microphone(
                        pcm, timestamp=capture_timestamp
                    )
                    future.result(timeout=5)
        except Exception as exc:
            if not self.stop_event.is_set():
                self._terminal_error("INPUT DEVICE ERROR", exc)
                self._request_transport_close()

    def _record_input_signal(self, pcm: bytes) -> None:
        samples = array("h")
        samples.frombytes(pcm)
        if sys.byteorder != "little":
            samples.byteswap()
        if samples:
            square_sum = float(sum(sample * sample for sample in samples))
            peak = max(abs(sample) for sample in samples)
            block_rms = math.sqrt(square_sum / len(samples))
        else:
            square_sum = 0.0
            peak = 0
            block_rms = 0.0
        with self._lock:
            self.captured_blocks += 1
            self.captured_bytes += len(pcm)
            self.input_sample_count += len(samples)
            self.input_square_sum += square_sum
            self.input_peak = max(self.input_peak, peak)
            if block_rms <= SILENT_RMS_THRESHOLD:
                self.silent_blocks += 1

    def _playback(self) -> None:
        while not self.stop_event.is_set() and not self.session_ready.wait(0.05):
            pass
        if self.stop_event.is_set():
            return
        try:
            with self.audio_backend.RawOutputStream(
                samplerate=OUTPUT_RATE,
                blocksize=0,
                device=self.config.output_device.index,
                channels=CHANNELS,
                dtype=DTYPE,
            ) as stream:
                self._emit(
                    "audio.output.opened",
                    device_index=self.config.output_device.index,
                    rate=OUTPUT_RATE,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    blocksize=0,
                )
                while not self.stop_event.is_set():
                    queued = self.playback_queue.get()
                    if queued is self._playback_sentinel:
                        return
                    assert isinstance(queued, PlaybackSlice)
                    if not self._commit_playback_slice(queued):
                        self._emit(
                            "audio.playback.stale_slice_discarded",
                            response_id=queued.response_id,
                            playback_epoch=queued.epoch,
                            slice_sequence=queued.sequence,
                            bytes=len(queued.pcm),
                        )
                        continue
                    self.correlation_probe.submit_playback(
                        queued.pcm,
                        timestamp=self.clock(),
                        response_id=queued.response_id,
                        epoch=queued.epoch,
                        sequence=queued.sequence,
                    )
                    try:
                        stream.write(queued.pcm)
                    except Exception:
                        self._abandon_current_write(queued)
                        raise
                    completed_after_interrupt = self._complete_playback_slice(queued)
                    if completed_after_interrupt:
                        self._emit(
                            "audio.playback.current_write_completed_after_interrupt",
                            response_id=queued.response_id,
                            playback_epoch=queued.epoch,
                            slice_sequence=queued.sequence,
                            bytes=len(queued.pcm),
                            application_stop_latency_estimate_ms=(
                                self.application_stop_latency_estimate_ms
                            ),
                        )
        except Exception as exc:
            if not self.stop_event.is_set():
                self._terminal_error("OUTPUT DEVICE ERROR", exc)
                self._request_transport_close()

    def _commit_playback_slice(self, playback_slice: PlaybackSlice) -> bool:
        with self._lock:
            state = self.response_playback.get(playback_slice.response_id)
            valid = (
                state is not None
                and state.epoch == playback_slice.epoch
                and not state.playback_invalidated
            )
            if not valid:
                self._record_stale_slice(playback_slice, state)
                return False
            self._current_write = playback_slice
            self._current_write_started_monotonic = self.clock()
            self._current_write_interrupted_at = None
            self.current_write_response_id = playback_slice.response_id
            self.current_write_epoch = playback_slice.epoch
            self.current_write_sequence = playback_slice.sequence
            self.current_write_bytes = len(playback_slice.pcm)
            self.current_write_started_at = utc_now()
            self.current_write_completed_at = None
            self.current_write_completed_after_interrupt = False
            return True

    def _complete_playback_slice(self, playback_slice: PlaybackSlice) -> bool:
        completed_at = self.clock()
        with self._lock:
            started_at = self._current_write_started_monotonic
            duration_ms = (
                max(0.0, (completed_at - started_at) * 1000)
                if started_at is not None
                else 0.0
            )
            self.max_current_write_duration_ms = max(
                self.max_current_write_duration_ms, duration_ms
            )
            state = self.response_playback.get(playback_slice.response_id)
            if state is not None:
                state.slices_written += 1
            self.playback_writes += 1
            self.playback_bytes += len(playback_slice.pcm)
            self.total_slices_written += 1
            completed_after_interrupt = self._current_write_interrupted_at is not None
            if completed_after_interrupt:
                self.current_write_completed_after_interrupt_count += 1
                assert self._current_write_interrupted_at is not None
                self.application_stop_latency_estimate_ms = round(
                    max(0.0, (completed_at - self._current_write_interrupted_at) * 1000),
                    2,
                )
            self.current_write_completed_at = utc_now()
            self.current_write_completed_after_interrupt = completed_after_interrupt
            self._current_write = None
            self._current_write_started_monotonic = None
            self._current_write_interrupted_at = None
            return completed_after_interrupt

    def _abandon_current_write(self, playback_slice: PlaybackSlice) -> None:
        with self._lock:
            if self._current_write == playback_slice:
                self._current_write = None
                self._current_write_started_monotonic = None
                self._current_write_interrupted_at = None

    def _record_stale_slice(
        self,
        playback_slice: PlaybackSlice,
        state: ResponsePlaybackState | None,
    ) -> None:
        byte_count = len(playback_slice.pcm)
        self.stale_slices_discarded_count += 1
        self.stale_bytes_discarded += byte_count
        if state is not None:
            state.slices_discarded_stale += 1
            state.stale_bytes += byte_count

    def _request_transport_close(self) -> None:
        loop = self.loop
        transport = self.transport
        if loop is not None and transport is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(transport.close(), loop)

    def _interrupt_playback(self) -> None:
        invalidated_ids: list[str] = []
        removed_slices = 0
        removed_bytes = 0
        current_write_active = False
        with self._lock:
            self.playback_invalidation_request_count += 1
            states_to_invalidate = [
                state
                for state in self.response_playback.values()
                if not state.playback_invalidated
                and (
                    state.outstanding_slices > 0
                    or state.response_id == self.active_playback_response_id
                )
            ]
            had_active_playback = any(
                state.outstanding_slices > 0 for state in states_to_invalidate
            )
            for state in states_to_invalidate:
                state.playback_invalidated = True
                invalidated_ids.append(state.response_id)
            if had_active_playback:
                self.active_response_invalidation_count += 1
                self.playback_interruption_count += 1
            if self.active_playback_response_id in invalidated_ids:
                self.active_playback_response_id = None
            current = self._current_write
            if current is not None and current.response_id in invalidated_ids:
                current_write_active = True
                self.current_write_active_at_interrupt_count += 1
                if self._current_write_interrupted_at is None:
                    self._current_write_interrupted_at = self.clock()

            retained: list[PlaybackSlice | object] = []
            while True:
                try:
                    item = self.playback_queue.get_nowait()
                except queue.Empty:
                    break
                if item is self._playback_sentinel:
                    retained.append(item)
                    continue
                assert isinstance(item, PlaybackSlice)
                if item.response_id in invalidated_ids:
                    byte_count = len(item.pcm)
                    removed_slices += 1
                    removed_bytes += byte_count
                    state = self.response_playback.get(item.response_id)
                    if state is not None:
                        state.slices_removed += 1
                        state.removed_bytes += byte_count
                else:
                    retained.append(item)
            for item in retained:
                self.playback_queue.put(item)

            self.queued_slices_removed_count += removed_slices
            self.queued_bytes_removed += removed_bytes
            if not current_write_active:
                self.application_stop_latency_estimate_ms = 0.0

        fields: dict[str, object] = {
            "response_ids": invalidated_ids,
            "queued_slices_removed": removed_slices,
            "queued_bytes_removed": removed_bytes,
            "current_write_active": current_write_active,
        }
        self._emit("audio.playback.invalidated", **fields)
        self._emit(
            "audio.playback.interrupted",
            queued_chunks_removed=removed_slices,
            queued_bytes_removed=removed_bytes,
            current_write_active=current_write_active,
        )

    def handle_event(self, event: dict[str, Any]) -> None:
        now = self.clock()
        kind = str(event.get("type") or "unknown")
        if kind == "session.created":
            session = event.get("session") or {}
            self.session_id = str(session.get("id") or "")
            self.session_created_at = utc_now()
            self._emit(kind, session_id=self.session_id)
        elif kind == "session.updated":
            self.session_updated_at = utc_now()
            self.session_ready.set()
            self._emit(kind, session_id=self.session_id)
            self._status("Connected")
        elif kind == "input_audio_buffer.speech_started":
            self.speech_started_count += 1
            self.speech_started_seen_count += 1
            self._emit(
                kind,
                item_id=event.get("item_id"),
                audio_start_ms=event.get("audio_start_ms"),
            )
            response_id, epoch = self._current_probe_playback_identity()
            self.correlation_probe.submit_speech_start(
                timestamp=now,
                wall_timestamp=utc_now(),
                item_id=str(event.get("item_id")) if event.get("item_id") else None,
                current_response_id=response_id,
                current_epoch=epoch,
            )
            self._interrupt_playback()
        elif kind == "input_audio_buffer.speech_stopped":
            self.speech_stopped_count += 1
            self.last_speech_stopped = now
            self._emit(
                kind,
                item_id=event.get("item_id"),
                audio_end_ms=event.get("audio_end_ms"),
            )
        elif kind == "conversation.item.input_audio_transcription.completed":
            self.transcription_count += 1
            self._emit(kind, item_id=event.get("item_id"), transcript=event.get("transcript", ""))
        elif kind == "conversation.item.input_audio_transcription.failed":
            self.transcription_failures += 1
            self._emit(kind, item_id=event.get("item_id"), error=event.get("error"))
        elif kind == "response.created":
            response = event.get("response") or {}
            response_id = str(response.get("id") or event.get("response_id") or "unknown")
            self.responses[response_id] = ResponseMetric(response_id, now)
            self.latest_response_id = response_id
            self.response_count += 1
            with self._lock:
                self.playback_epoch += 1
                self.response_playback[response_id] = ResponsePlaybackState(
                    response_id=response_id,
                    epoch=self.playback_epoch,
                )
                self.active_playback_response_id = response_id
            self._emit(kind, response_id=response_id, status=response.get("status"))
        elif kind == "response.output_audio.delta":
            self._handle_audio_delta(event, now)
        elif kind in {"response.output_audio.done", "response.output_item.done"}:
            self._emit(kind, response_id=event.get("response_id"), item_id=event.get("item_id"))
        elif kind in {"response.output_audio_transcript.delta", "response.output_text.delta"}:
            self._emit(kind, response_id=event.get("response_id"), delta=event.get("delta", ""))
        elif kind in {"response.output_audio_transcript.done", "response.output_text.done"}:
            self._emit(
                kind,
                response_id=event.get("response_id"),
                transcript=event.get("transcript") or event.get("text") or "",
            )
        elif kind == "response.done":
            response = event.get("response") or {}
            response_id = str(response.get("id") or event.get("response_id") or self.latest_response_id or "unknown")
            metric = self.responses.setdefault(response_id, ResponseMetric(response_id, now))
            metric.status = str(response.get("status") or "")
            metric.response_completed = metric.status == "completed"
            with self._lock:
                playback = self.response_playback.get(response_id)
                if playback is not None:
                    playback.provider_response_status = metric.status
                    playback.provider_done = True
                if self.active_playback_response_id == response_id:
                    self.active_playback_response_id = None
            self._emit(kind, **metric.summary())
        elif kind == "error":
            error = event.get("error") or {}
            message = sanitize_text(error.get("message") or error, self.config.api_key)
            self.server_errors.append(message)
            self._error_seen = True
            self._emit(
                "server.error",
                error_type=error.get("type") if isinstance(error, dict) else None,
                code=error.get("code") if isinstance(error, dict) else None,
                message=message,
                param=error.get("param") if isinstance(error, dict) else None,
            )
            self._status("SERVER ERROR")
            self.stop_event.set()
            self.session_ready.set()
            self.playback_queue.put(self._playback_sentinel)
        else:
            self._emit(kind)

    def _handle_audio_delta(self, event: dict[str, Any], now: float) -> None:
        pcm = decode_output_audio(event)
        response_id = str(event.get("response_id") or self.latest_response_id or "unknown")
        metric = self.responses.setdefault(response_id, ResponseMetric(response_id, now))
        self.latest_response_id = response_id
        metric.add_audio(len(pcm), now, self.last_speech_stopped)
        pcm_slices = split_playback_pcm(pcm)
        with self._lock:
            playback = self.response_playback.get(response_id)
            if playback is None:
                playback = ResponsePlaybackState(
                    response_id=response_id,
                    epoch=None,
                    playback_invalidated=True,
                )
                self.response_playback[response_id] = playback
            playback.provider_audio_bytes += len(pcm)
            first_sequence = playback.slices_created + 1
            playback.slices_created += len(pcm_slices)
            self.total_slices_created += len(pcm_slices)
            if pcm_slices and len(pcm_slices[-1]) < PLAYBACK_SLICE_BYTES:
                self.short_final_slices += 1
            if pcm_slices:
                self.max_slice_bytes = max(
                    self.max_slice_bytes, max(len(item) for item in pcm_slices)
                )
            queued = (
                playback.epoch is not None
                and not playback.playback_invalidated
                and not playback.provider_done
            )
            if queued:
                assert playback.epoch is not None
                for offset, item in enumerate(pcm_slices):
                    self.playback_queue.put(
                        PlaybackSlice(
                            response_id=response_id,
                            epoch=playback.epoch,
                            sequence=first_sequence + offset,
                            pcm=item,
                        )
                    )
            else:
                for offset, item in enumerate(pcm_slices):
                    self._record_stale_slice(
                        PlaybackSlice(
                            response_id=response_id,
                            epoch=playback.epoch if playback.epoch is not None else -1,
                            sequence=first_sequence + offset,
                            pcm=item,
                        ),
                        playback,
                    )
        first_latency = metric.first_audio_latency_ms
        self._emit(
            "response.output_audio.delta",
            response_id=response_id,
            delta_index=metric.delta_count,
            bytes=len(pcm),
            queued=queued,
            playback_slice_count=len(pcm_slices),
            first_audio_latency_ms=(
                round(first_latency, 2)
                if metric.delta_count == 1 and first_latency is not None
                else None
            ),
            latency_basis=metric.latency_basis if metric.delta_count == 1 else None,
        )
        if queued and pcm_slices:
            self._emit(
                "audio.playback.slices_enqueued",
                response_id=response_id,
                playback_epoch=playback.epoch,
                slices=len(pcm_slices),
                bytes=len(pcm),
            )
        elif pcm_slices:
            self._emit(
                "audio.playback.stale_delta_discarded",
                response_id=response_id,
                playback_epoch=playback.epoch,
                slices=len(pcm_slices),
                bytes=len(pcm),
            )

    def _current_probe_playback_identity(self) -> tuple[str | None, int | None]:
        """Observe response ownership without changing playback state."""

        with self._lock:
            if self._current_write is not None:
                return self._current_write.response_id, self._current_write.epoch
            candidates = [
                state
                for state in self.response_playback.values()
                if not state.playback_invalidated and state.outstanding_slices > 0
            ]
            if not candidates:
                return None, None
            newest = max(candidates, key=lambda state: state.epoch or -1)
            return newest.response_id, newest.epoch

    def latest_response_summary(self) -> dict[str, object]:
        metric = self.responses.get(self.latest_response_id or "")
        return metric.summary() if metric is not None else {
            "first_audio_latency_ms": None,
            "latency_basis": None,
            "delta_count": 0,
            "decoded_bytes": 0,
            "total_audio_duration_ms": 0.0,
            "max_delta_gap_ms": None,
            "average_delta_gap_ms": None,
            "status": None,
            "response_completed": False,
        }

    def report(self) -> dict[str, object]:
        with self._lock:
            captured_blocks = self.captured_blocks
            input_rms = (
                math.sqrt(self.input_square_sum / self.input_sample_count)
                if self.input_sample_count
                else 0.0
            )
            silent_ratio = self.silent_blocks / captured_blocks if captured_blocks else 0.0
            timeline = list(self.timeline)
            current_write = self._current_write
            playback_summaries = [
                state.summary(current_write) for state in self.response_playback.values()
            ]
            slicing_report = {
                "slice_duration_target_ms": PLAYBACK_SLICE_MS,
                "slice_target_bytes": PLAYBACK_SLICE_BYTES,
                "total_slices_created": self.total_slices_created,
                "total_slices_written": self.total_slices_written,
                "short_final_slices": self.short_final_slices,
                "max_slice_bytes": self.max_slice_bytes,
                "max_slice_duration_ms": audio_duration_ms(self.max_slice_bytes),
            }
            interruption_report = {
                "speech_started_seen_count": self.speech_started_seen_count,
                "playback_invalidation_request_count": (
                    self.playback_invalidation_request_count
                ),
                "active_response_invalidation_count": (
                    self.active_response_invalidation_count
                ),
                "queued_slices_removed_count": self.queued_slices_removed_count,
                "queued_bytes_removed": self.queued_bytes_removed,
                "stale_slices_discarded_count": self.stale_slices_discarded_count,
                "stale_bytes_discarded": self.stale_bytes_discarded,
                "current_write_active_at_interrupt_count": (
                    self.current_write_active_at_interrupt_count
                ),
                "current_write_completed_after_interrupt_count": (
                    self.current_write_completed_after_interrupt_count
                ),
                "max_current_write_duration_ms": round(
                    self.max_current_write_duration_ms, 2
                ),
                "application_stop_latency_estimate_ms": (
                    self.application_stop_latency_estimate_ms
                ),
                "current_write_active": current_write is not None,
                "current_write_response_id": self.current_write_response_id,
                "current_write_epoch": self.current_write_epoch,
                "current_write_sequence": self.current_write_sequence,
                "current_write_bytes": self.current_write_bytes,
                "current_write_started_at": self.current_write_started_at,
                "current_write_completed_at": self.current_write_completed_at,
                "current_write_completed_after_interrupt": (
                    self.current_write_completed_after_interrupt
                ),
            }
        latest = self.latest_response_summary()
        correlation_report = self.correlation_probe.report()
        report = {
            "APPLICATION": {
                "app_name": APP_NAME,
                "app_version": APP_VERSION,
                "timestamp": utc_now(),
                "os_platform": platform.platform(),
                "python_runtime": sys.version.replace("\n", " "),
                "dependencies": {
                    "sounddevice": dependency_version("sounddevice"),
                    "aiohttp": dependency_version("aiohttp"),
                    "yandex_ai_studio_sdk": "not used (deterministic sounddevice wrapper)",
                },
            },
            "YANDEX SESSION": {
                "endpoint": ENDPOINT,
                "model_uri": f"gpt://{safe_folder_id(self.config.folder_id)}/{self.config.model}",
                "folder_id": safe_folder_id(self.config.folder_id),
                "voice": self.config.voice,
                "language": self.config.language,
                "instructions_summary": self.config.instructions,
                "input_format": "headerless signed PCM16 little-endian mono",
                "input_rate_hz": INPUT_RATE,
                "output_format": "headerless signed PCM16 little-endian mono",
                "output_rate_hz": OUTPUT_RATE,
                "vad": {
                    "type": "server_vad",
                    "threshold": VAD_THRESHOLD,
                    "silence_duration_ms": VAD_SILENCE_MS,
                },
                "start_time": self.started_at,
                "stop_time": self.stopped_at,
                "session_id": self.session_id,
            },
            "INPUT DEVICE": self._device_report(self.config.input_device, "input"),
            "OUTPUT DEVICE": self._device_report(self.config.output_device, "output"),
            "INPUT SIGNAL": {
                "captured_blocks": captured_blocks,
                "captured_bytes": self.captured_bytes,
                "rms_pcm16": round(input_rms, 2),
                "peak_pcm16": self.input_peak,
                "silent_block_ratio": round(silent_ratio, 4),
                "speech_started_count": self.speech_started_count,
                "speech_started_seen_count": self.speech_started_seen_count,
                "speech_stopped_count": self.speech_stopped_count,
                "transcription_count": self.transcription_count,
                "transcription_failures": self.transcription_failures,
            },
            "NETWORK": {
                "connect_time_ms": self.connect_time_ms,
                "connected_at": self.connected_at,
                "session_created_at": self.session_created_at,
                "session_updated_at": self.session_updated_at,
                "close_time": self.close_time,
                "close": self.websocket_close,
                "server_errors": list(self.server_errors),
                "transport_errors": list(self.transport_errors),
            },
            "RESPONSE/AUDIO": {
                "response_count": self.response_count,
                **latest,
                "playback_writes": self.playback_writes,
                "playback_bytes": self.playback_bytes,
                "playback_interruption_count": self.playback_interruption_count,
                "all_responses": [metric.summary() for metric in self.responses.values()],
            },
            "PLAYBACK SLICING": slicing_report,
            "INTERRUPTION": interruption_report,
            "RESPONSE-SCOPED PLAYBACK": {
                "responses": playback_summaries,
            },
            "PLAYBACK/MIC CORRELATION PROBE": correlation_report,
            "EVENT TIMELINE": timeline,
        }
        return sanitize_value(report, self.config.api_key)  # type: ignore[return-value]

    @staticmethod
    def _device_report(device: AudioDevice, direction: str) -> dict[str, object]:
        return {
            **asdict(device),
            "actual_opened_sample_rate": INPUT_RATE if direction == "input" else OUTPUT_RATE,
            "channels": CHANNELS,
            "dtype": DTYPE,
            "block_size_frames": INPUT_FRAMES if direction == "input" else 0,
            "stream_mode": "persistent blocking RawInputStream"
            if direction == "input"
            else "persistent blocking RawOutputStream",
        }

    def diagnostic_text(self) -> str:
        return format_diagnostic_report(self.report(), self.config.api_key)


def format_diagnostic_report(report: dict[str, object], api_key: str = "") -> str:
    lines = [f"{APP_NAME} v{APP_VERSION}", "Standalone diagnostic report", ""]
    for section, content in report.items():
        lines.append(f"[{section}]")
        if section == "EVENT TIMELINE" and isinstance(content, list):
            for record in content:
                if not isinstance(record, dict):
                    continue
                timestamp = record.get("timestamp", "")
                event = record.get("event", "")
                fields = {key: value for key, value in record.items() if key not in {"timestamp", "event"}}
                details = json.dumps(fields, ensure_ascii=False, separators=(",", ":")) if fields else ""
                lines.append(f"{timestamp}  {event}{'  ' + details if details else ''}")
        elif isinstance(content, dict):
            for key, value in content.items():
                rendered = (
                    json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                lines.append(f"{key}: {rendered}")
        else:
            lines.append(str(content))
        lines.append("")
    return sanitize_text("\n".join(lines).rstrip() + "\n", api_key)


def write_diagnostic_report(path: Path, report_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text, encoding="utf-8")
