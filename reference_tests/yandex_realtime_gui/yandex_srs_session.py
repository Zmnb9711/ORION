"""Isolated SRS Radio sibling session for the standalone Yandex tester."""

from __future__ import annotations

import asyncio
import platform
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import aiohttp
import samplerate

from srs_opus import OPUS_FRAME_BYTES, OpusDecoder, OpusEncoder, OpusLibrary
from srs_protocol import (
    AM,
    Frequency,
    SrsProtocolError,
    VoicePacket,
    decode_voice_packet,
    encode_voice_packet,
    mask_guid,
)
from srs_radio_client import SrsRadioClient, SrsRadioConfig, SrsState
from srs_resampler import StreamingPcm16Resampler, make_rx_resampler, make_tx_resampler
from srs_transmission import PacketDecision, TransmissionTracker, TxPacer, split_tx_pcm
from yandex_reference_core import (
    APP_NAME,
    AiohttpTransport,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    INPUT_FRAMES,
    INPUT_RATE,
    RealtimeTransport,
    build_model_uri,
    build_session_update,
    build_url,
    decode_output_audio,
    dependency_version,
    encode_input_audio_event,
    format_diagnostic_report,
    safe_folder_id,
    sanitize_text,
    sanitize_value,
    utc_now,
)

SRS_APP_VERSION = "SRS Radio v0.1"
YANDEX_BLOCK_BYTES = INPUT_FRAMES * 2
TRAILING_SILENCE_MS = 400
TRAILING_SILENCE_BLOCKS = TRAILING_SILENCE_MS // 20
RESPONSE_MAX_SECONDS = 30
RESPONSE_MAX_BYTES = INPUT_RATE * 2 * RESPONSE_MAX_SECONDS

EventCallback = Callable[[str, dict[str, object]], None]


@dataclass(frozen=True, slots=True)
class SrsSessionConfig:
    api_key: str
    folder_id: str
    model: str = DEFAULT_MODEL
    voice: str = DEFAULT_VOICE
    language: str = DEFAULT_LANGUAGE
    instructions: str = DEFAULT_INSTRUCTIONS
    srs: SrsRadioConfig = field(default_factory=SrsRadioConfig)

    def validate(self) -> None:
        if not self.api_key.strip():
            raise ValueError("API key is required.")
        build_model_uri(self.folder_id, self.model)
        if not self.voice.strip():
            raise ValueError("Voice is required.")
        if not self.language.strip():
            raise ValueError("Language is required.")
        self.srs.validate()


@dataclass(slots=True)
class PreparedResponse:
    response_id: str
    pcm44: bytes
    created_at: float


@dataclass(slots=True)
class ResponseBuffer:
    response_id: str
    created_at: float
    pcm: bytearray = field(default_factory=bytearray)
    delta_count: int = 0
    first_audio_at: float | None = None
    audio_done: bool = False
    response_done: bool = False
    status: str | None = None
    dropped_reason: str | None = None
    queued: bool = False

    def summary(self) -> dict[str, object]:
        return {
            "response_id": self.response_id,
            "status": self.status,
            "delta_count": self.delta_count,
            "response_bytes": len(self.pcm),
            "audio_done": self.audio_done,
            "response_done": self.response_done,
            "dropped_reason": self.dropped_reason,
            "queued_for_radio_tx": self.queued,
            "first_audio_latency_ms": (
                round((self.first_audio_at - self.created_at) * 1000, 2)
                if self.first_audio_at is not None
                else None
            ),
        }


class YandexSrsReferenceSession:
    """Headless SRS↔Yandex bridge; it never enumerates or opens PortAudio."""

    def __init__(
        self,
        config: SrsSessionConfig,
        callback: EventCallback,
        *,
        transport_factory: Callable[[], RealtimeTransport] = AiohttpTransport,
        radio_factory: Callable[..., SrsRadioClient] = SrsRadioClient,
        decoder_factory: Callable[[], OpusDecoder] = OpusDecoder,
        encoder_factory: Callable[[], OpusEncoder] = OpusEncoder,
        rx_resampler_factory: Callable[[], StreamingPcm16Resampler] = make_rx_resampler,
        tx_resampler_factory: Callable[[], StreamingPcm16Resampler] = make_tx_resampler,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        config.validate()
        self.config = config
        self.callback = callback
        self.transport_factory = transport_factory
        self.radio_factory = radio_factory
        self.decoder_factory = decoder_factory
        self.encoder_factory = encoder_factory
        self.rx_resampler_factory = rx_resampler_factory
        self.tx_resampler_factory = tx_resampler_factory
        self.clock = clock
        self.stop_event = threading.Event()
        self.session_ready = threading.Event()
        self.thread: threading.Thread | None = None
        self.tx_thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.transport: RealtimeTransport | None = None
        self.radio: SrsRadioClient | None = None
        self.decoder: OpusDecoder | None = None
        self.encoder: OpusEncoder | None = None
        self.rx_resampler: StreamingPcm16Resampler | None = None
        self.tx_resampler: StreamingPcm16Resampler | None = None
        self.tracker: TransmissionTracker | None = None
        self.input_blocks: queue.Queue[bytes] = queue.Queue()
        self.tx_queue: queue.Queue[PreparedResponse | object] = queue.Queue(maxsize=1)
        self._tx_sentinel = object()
        self._lock = threading.RLock()
        self._rx_accumulator = bytearray()
        self._packet_id = 1
        self.responses: dict[str, ResponseBuffer] = {}
        self.latest_response_id: str | None = None
        self.timeline: list[dict[str, object]] = []
        self.errors: list[str] = []
        self.started_at: str | None = None
        self.stopped_at: str | None = None
        self.connect_time_ms: float | None = None
        self.yandex_session_id: str | None = None
        self._error_seen = False
        self._manual_stop_requested = False
        self._rx_end_injected_for_timestamp: float | None = None
        self.malformed_packets = 0
        self.opus_decode_errors = 0
        self.decoded_samples = 0
        self.resampled_rx_samples = 0
        self.yandex_blocks_sent = 0
        self.trailing_silence_blocks = 0
        self.trailing_silence_bytes = 0
        self.rx_transmissions_completed = 0
        self.tx_transmissions = 0
        self.tx_frames = 0
        self.final_padding_samples = 0
        self.tx_jitter_reports: list[dict[str, object]] = []
        self.responses_dropped = 0

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        if self.thread is not None:
            raise RuntimeError("A session object cannot be restarted; create a new session.")
        self.started_at = utc_now()
        self.thread = threading.Thread(
            target=self._thread_main, name="yandex-srs-network", daemon=True
        )
        self.thread.start()

    def stop(self, wait: bool = False, timeout: float = 3.0) -> None:
        self._manual_stop_requested = True
        self.stop_event.set()
        self.session_ready.set()
        try:
            self.tx_queue.put_nowait(self._tx_sentinel)
        except queue.Full:
            self._discard_queued_tx()
            self.tx_queue.put_nowait(self._tx_sentinel)
        radio = self.radio
        if radio is not None:
            radio.close()
        loop = self.loop
        transport = self.transport
        if loop is not None and transport is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(transport.close(), loop)
        if wait and self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout)
        if self.thread is None or not self.thread.is_alive():
            self._status("STOPPED")

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            self._terminal_error("SRS SESSION ERROR", exc)

    async def _run(self) -> None:
        self.loop = asyncio.get_running_loop()
        input_task: asyncio.Task[None] | None = None
        try:
            self._status("CONNECTING_TCP")
            self.radio = self.radio_factory(
                self.config.srs, self._on_radio_datagram, self._on_radio_event
            )
            self.decoder = self.decoder_factory()
            self.encoder = self.encoder_factory()
            self.rx_resampler = self.rx_resampler_factory()
            self.tx_resampler = self.tx_resampler_factory()
            self.tracker = TransmissionTracker(
                own_client_guid=self.radio.client_guid,
                frequency_hz=self.config.srs.frequency_hz,
                modulation=self.config.srs.modulation,
            )
            await asyncio.to_thread(self.radio.connect)
            if self.stop_event.is_set():
                return
            self._status("Connecting Yandex")
            self.transport = self.transport_factory()
            started = self.clock()
            await self.transport.connect(
                build_url(self.config.folder_id, self.config.model),
                {"Authorization": f"Api-Key {self.config.api_key}"},
            )
            self.connect_time_ms = round((self.clock() - started) * 1000, 2)
            await self.transport.send_json(build_session_update(self.config))  # type: ignore[arg-type]
            self._emit("session.update.sent")
            self.tx_thread = threading.Thread(
                target=self._tx_worker, name="srs-radio-tx", daemon=True
            )
            self.tx_thread.start()
            input_task = asyncio.create_task(self._input_sender())

            while not self.stop_event.is_set():
                if self.radio.stop_event.is_set() and self.radio.state is SrsState.ERROR:
                    raise ConnectionError("SRS transport entered ERROR state.")
                self._poll_rx_end()
                try:
                    message = await asyncio.wait_for(self.transport.receive(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                if message.event is not None:
                    self.handle_event(message.event)
                if message.close_code is not None or (
                    message.event is None and message.close_reason
                ):
                    raise ConnectionError(
                        f"Yandex WebSocket closed: code={message.close_code}, reason={message.close_reason}"
                    )
        except aiohttp.WSServerHandshakeError as exc:
            category = "AUTH ERROR" if exc.status in {401, 403} else "YANDEX WEBSOCKET ERROR"
            self._terminal_error(category, exc)
        except Exception as exc:
            if not self.stop_event.is_set():
                self._terminal_error("SRS SESSION ERROR", exc)
        finally:
            self.stop_event.set()
            self.session_ready.set()
            if input_task is not None:
                input_task.cancel()
                await asyncio.gather(input_task, return_exceptions=True)
            self._discard_queued_tx()
            try:
                self.tx_queue.put_nowait(self._tx_sentinel)
            except queue.Full:
                pass
            if self.transport is not None:
                try:
                    await self.transport.close()
                except Exception as exc:
                    self.errors.append(sanitize_text(exc, self.config.api_key))
            if self.radio is not None:
                await asyncio.to_thread(self.radio.close)
            if self.tx_thread is not None and self.tx_thread.is_alive():
                await asyncio.to_thread(self.tx_thread.join, 2.0)
            for codec in (self.decoder, self.encoder):
                if codec is not None:
                    codec.close()
            self.stopped_at = utc_now()
            if not self._error_seen or self._manual_stop_requested:
                self._status("STOPPED")
            self.loop = None

    async def _input_sender(self) -> None:
        while not self.stop_event.is_set() and not self.session_ready.wait(0.02):
            await asyncio.sleep(0)
        while not self.stop_event.is_set():
            try:
                pcm = self.input_blocks.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.005)
                continue
            transport = self.transport
            if transport is None:
                return
            await transport.send_json(encode_input_audio_event(pcm))
            self.yandex_blocks_sent += 1

    def _on_radio_event(self, event: str, fields: dict[str, object]) -> None:
        self._emit(event, **fields)
        if event == "srs.state":
            value = str(fields.get("value") or "")
            if value:
                self._status(value)

    def _on_radio_datagram(self, datagram: bytes) -> None:
        try:
            packet = decode_voice_packet(datagram)
        except SrsProtocolError as exc:
            self.malformed_packets += 1
            self._emit("srs.udp.malformed", message=str(exc), count=self.malformed_packets)
            return
        tracker = self.tracker
        decoder = self.decoder
        resampler = self.rx_resampler
        if tracker is None or decoder is None or resampler is None:
            return
        with self._lock:
            decision = tracker.accept(packet, self.clock())
            if decision is not PacketDecision.ACCEPTED:
                self._emit("srs.rx.dropped", decision=decision.value)
                return
            self._rx_end_injected_for_timestamp = None
            try:
                decoded = decoder.decode(packet.audio)
            except Exception as exc:
                self.opus_decode_errors += 1
                self._emit("srs.opus.decode_error", message=str(exc), count=self.opus_decode_errors)
                return
            self.decoded_samples += len(decoded) // 2
            resampled = resampler.process(decoded)
            self.resampled_rx_samples += len(resampled) // 2
            self._rx_accumulator.extend(resampled)
            while len(self._rx_accumulator) >= YANDEX_BLOCK_BYTES:
                block = bytes(self._rx_accumulator[:YANDEX_BLOCK_BYTES])
                del self._rx_accumulator[:YANDEX_BLOCK_BYTES]
                self.input_blocks.put(block)
            self._emit(
                "srs.rx.packet",
                sender_guid=mask_guid(packet.original_client_guid),
                sender_name=self._sender_name(packet.original_client_guid),
                packet_id=packet.packet_id,
                opus_bytes=len(packet.audio),
                decoded_samples=len(decoded) // 2,
                resampled_samples=len(resampled) // 2,
            )

    def _sender_name(self, guid: str) -> str | None:
        radio = self.radio
        if radio is None:
            return None
        client = radio.clients.get(guid)
        return str(client.get("Name")) if isinstance(client, dict) and client.get("Name") else None

    def _poll_rx_end(self) -> None:
        tracker = self.tracker
        if tracker is None:
            return
        now = self.clock()
        with self._lock:
            last_packet_at = tracker.last_human_packet_at
            completed = tracker.expire(now)
            if completed is None or last_packet_at is None:
                return
            if self._rx_end_injected_for_timestamp == last_packet_at:
                return
            if self._rx_accumulator:
                missing = YANDEX_BLOCK_BYTES - len(self._rx_accumulator)
                self._rx_accumulator.extend(bytes(missing))
                self.input_blocks.put(bytes(self._rx_accumulator))
                self._rx_accumulator.clear()
                self.trailing_silence_bytes += missing
            zero_block = bytes(YANDEX_BLOCK_BYTES)
            for _ in range(TRAILING_SILENCE_BLOCKS):
                self.input_blocks.put(zero_block)
            self.trailing_silence_blocks += TRAILING_SILENCE_BLOCKS
            self.trailing_silence_bytes += TRAILING_SILENCE_BLOCKS * YANDEX_BLOCK_BYTES
            self.rx_transmissions_completed += 1
            self._rx_end_injected_for_timestamp = last_packet_at
            self._emit(
                "srs.rx.transmission_completed",
                sender_guid=mask_guid(completed),
                trailing_silence_ms=TRAILING_SILENCE_MS,
            )

    def handle_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("type") or "unknown")
        now = self.clock()
        if kind == "session.created":
            session = event.get("session") or {}
            self.yandex_session_id = str(session.get("id") or "")
            self._emit(kind, session_id=self.yandex_session_id)
        elif kind == "session.updated":
            self.session_ready.set()
            self._status("READY")
            self._emit(kind, session_id=self.yandex_session_id)
        elif kind in {
            "input_audio_buffer.speech_started",
            "input_audio_buffer.speech_stopped",
            "conversation.item.input_audio_transcription.failed",
        }:
            fields = {
                key: value
                for key, value in event.items()
                if key in {"item_id", "audio_start_ms", "audio_end_ms", "transcript", "error"}
            }
            self._emit(kind, **fields)
        elif kind == "conversation.item.input_audio_transcription.completed":
            transcript = str(event.get("transcript") or "")
            self._emit(
                kind,
                item_id=event.get("item_id"),
                transcript_persisted=False,
                transcript_characters=len(transcript),
            )
        elif kind == "response.created":
            response = event.get("response") or {}
            response_id = str(response.get("id") or event.get("response_id") or "unknown")
            self.responses[response_id] = ResponseBuffer(response_id, now)
            self.latest_response_id = response_id
            self._emit(kind, response_id=response_id, status=response.get("status"))
        elif kind == "response.output_audio.delta":
            self._handle_output_delta(event, now)
        elif kind == "response.output_audio.done":
            response_id = str(event.get("response_id") or self.latest_response_id or "unknown")
            response = self.responses.setdefault(response_id, ResponseBuffer(response_id, now))
            response.audio_done = True
            self._emit(kind, response_id=response_id)
            self._maybe_prepare(response)
        elif kind == "response.done":
            payload = event.get("response") or {}
            response_id = str(payload.get("id") or event.get("response_id") or self.latest_response_id or "unknown")
            response = self.responses.setdefault(response_id, ResponseBuffer(response_id, now))
            response.status = str(payload.get("status") or "")
            response.response_done = True
            if response.status != "completed":
                response.dropped_reason = f"provider status {response.status or 'unknown'}"
                self.responses_dropped += 1
            self._emit(kind, **response.summary())
            self._maybe_prepare(response)
        elif kind == "error":
            error = event.get("error") or {}
            message = sanitize_text(
                error.get("message") if isinstance(error, dict) else error, self.config.api_key
            )
            self._terminal_error("SERVER ERROR", RuntimeError(message))
        elif kind in {"response.output_audio_transcript.done", "response.output_text.done"}:
            self._emit(kind, response_id=event.get("response_id"))
        elif kind not in {"response.output_audio_transcript.delta", "response.output_text.delta"}:
            self._emit(kind)

    def _handle_output_delta(self, event: dict[str, Any], now: float) -> None:
        response_id = str(event.get("response_id") or self.latest_response_id or "unknown")
        response = self.responses.setdefault(response_id, ResponseBuffer(response_id, now))
        try:
            pcm = decode_output_audio(event)
        except ValueError as exc:
            response.dropped_reason = str(exc)
            self.responses_dropped += 1
            self._emit("response.output_audio.invalid", response_id=response_id, message=str(exc))
            return
        if len(pcm) % 2:
            response.dropped_reason = "provider PCM is not frame-aligned"
            self.responses_dropped += 1
            return
        if response.dropped_reason is not None:
            return
        if len(response.pcm) + len(pcm) > RESPONSE_MAX_BYTES:
            response.pcm.clear()
            response.dropped_reason = "radio response buffer limit exceeded"
            self.responses_dropped += 1
            self._emit(
                "response.radio_buffer_limit",
                response_id=response_id,
                limit_bytes=RESPONSE_MAX_BYTES,
            )
            return
        if response.first_audio_at is None:
            response.first_audio_at = now
        response.pcm.extend(pcm)
        response.delta_count += 1
        self._emit(
            "response.output_audio.delta",
            response_id=response_id,
            delta_index=response.delta_count,
            bytes=len(pcm),
            buffered_bytes=len(response.pcm),
        )

    def _maybe_prepare(self, response: ResponseBuffer) -> None:
        if response.queued or not response.audio_done or not response.response_done:
            return
        if response.status != "completed" or response.dropped_reason or not response.pcm:
            return
        prepared = PreparedResponse(response.response_id, bytes(response.pcm), response.created_at)
        try:
            self.tx_queue.put_nowait(prepared)
        except queue.Full:
            response.dropped_reason = "another radio response is already queued"
            response.pcm.clear()
            self.responses_dropped += 1
            return
        response.queued = True
        self._emit(
            "srs.tx.response_prepared",
            response_id=response.response_id,
            pcm_bytes=len(response.pcm),
        )

    def _tx_worker(self) -> None:
        pacer = TxPacer(clock=self.clock)
        while not self.stop_event.is_set():
            queued = self.tx_queue.get()
            if queued is self._tx_sentinel:
                return
            assert isinstance(queued, PreparedResponse)
            tracker = self.tracker
            radio = self.radio
            encoder = self.encoder
            resampler = self.tx_resampler
            if tracker is None or radio is None or encoder is None or resampler is None:
                return
            active_radio: SrsRadioClient = radio
            self._status("WAITING_FOR_TX")
            while not self.stop_event.wait(0.01):
                with self._lock:
                    if tracker.channel_clear(self.clock()):
                        tracker.bot_tx_active = True
                        break
            if self.stop_event.is_set():
                return
            self._status("TX")
            try:
                pcm16 = resampler.process(queued.pcm44, end_of_input=True)
                frames, padding = split_tx_pcm(pcm16, OPUS_FRAME_BYTES)
                encoded_frames = tuple(encoder.encode(frame) for frame in frames)
                self.final_padding_samples += padding

                def send_frame(opus: bytes, _: float) -> None:
                    packet = VoicePacket(
                        audio=opus,
                        frequencies=(
                            Frequency(
                                self.config.srs.frequency_hz,
                                self.config.srs.modulation,
                                0,
                            ),
                        ),
                        unit_id=self.config.srs.unit_id,
                        packet_id=self._packet_id,
                        retransmission_count=0,
                        original_client_guid=active_radio.client_guid,
                        current_sender_guid=active_radio.client_guid,
                    )
                    active_radio.send_voice(encode_voice_packet(packet))
                    self._packet_id += 1

                report = pacer.send(encoded_frames, send_frame, self.stop_event)
                self.tx_transmissions += 1
                self.tx_frames += report.sent_frames
                self.tx_jitter_reports.append(
                    {
                        "response_id": queued.response_id,
                        "scheduled_frames": report.scheduled_frames,
                        "sent_frames": report.sent_frames,
                        "median_jitter_ms": report.median_jitter_ms,
                        "max_jitter_ms": report.max_jitter_ms,
                        "cumulative_drift_ms": report.cumulative_drift_ms,
                    }
                )
                self._emit(
                    "srs.tx.completed",
                    response_id=queued.response_id,
                    frames=report.sent_frames,
                    final_padding_samples=padding,
                    max_jitter_ms=report.max_jitter_ms,
                )
            except Exception as exc:
                if not self.stop_event.is_set():
                    self._terminal_error("SRS TX ERROR", exc)
                    return
            finally:
                with self._lock:
                    tracker.bot_tx_active = False
                resampler.reset()  # complete provider response is a hard TX stream boundary
                response = self.responses.get(queued.response_id)
                if response is not None:
                    response.pcm.clear()
            if not self.stop_event.is_set():
                self._status("READY")

    def _discard_queued_tx(self) -> None:
        while True:
            try:
                item = self.tx_queue.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, PreparedResponse):
                response = self.responses.get(item.response_id)
                if response is not None:
                    response.pcm.clear()
                    response.dropped_reason = "manual stop before radio TX"

    def _terminal_error(self, category: str, exc: Exception) -> None:
        message = sanitize_text(exc, self.config.api_key)
        with self._lock:
            if self._error_seen and message in self.errors:
                return
            self._error_seen = True
            self.errors.append(message)
        self._emit("client.error", category=category, message=message, exception=type(exc).__name__)
        self._status("ERROR")
        self.stop_event.set()
        self.session_ready.set()

    def _status(self, value: str) -> None:
        self.callback("status", {"value": value})

    def _emit(self, event: str, **fields: object) -> None:
        safe = sanitize_value(fields, self.config.api_key)
        assert isinstance(safe, dict)
        record = {"timestamp": utc_now(), "event": event, **safe}
        with self._lock:
            self.timeline.append(record)
        self.callback(event, safe)

    def report(self) -> dict[str, object]:
        tracker = self.tracker
        radio_report = self.radio.report() if self.radio is not None else {}
        counters = tracker.counters if tracker is not None else None
        report = {
            "APPLICATION": {
                "app_name": APP_NAME,
                "app_version": SRS_APP_VERSION,
                "timestamp": utc_now(),
                "os_platform": platform.platform(),
                "python_runtime": sys.version.replace("\n", " "),
                "dependencies": {
                    "aiohttp": dependency_version("aiohttp"),
                    "samplerate": samplerate.__version__,
                    "libopus": OpusLibrary().version,
                    "sounddevice": "not used in SRS Radio mode",
                },
            },
            "YANDEX SESSION": {
                "model_uri": f"gpt://{safe_folder_id(self.config.folder_id)}/{self.config.model}",
                "folder_id": safe_folder_id(self.config.folder_id),
                "voice": self.config.voice,
                "language": self.config.language,
                "input_rate_hz": INPUT_RATE,
                "output_rate_hz": INPUT_RATE,
                "session_id": self.yandex_session_id,
                "start_time": self.started_at,
                "stop_time": self.stopped_at,
                "connect_time_ms": self.connect_time_ms,
            },
            "SRS CONFIG/LIFECYCLE": radio_report,
            "SRS RX": {
                "malformed_packets": self.malformed_packets,
                "opus_decode_errors": self.opus_decode_errors,
                "decoded_samples": self.decoded_samples,
                "resampled_samples": self.resampled_rx_samples,
                "transmissions_started": counters.transmissions_started if counters else 0,
                "transmissions_completed": counters.transmissions_completed if counters else 0,
                "duplicates": counters.duplicates if counters else 0,
                "out_of_order": counters.out_of_order if counters else 0,
                "sequence_gaps": counters.sequence_gaps if counters else 0,
                "collisions": counters.collisions if counters else 0,
                "self_packets_dropped": counters.self_packets_dropped if counters else 0,
            },
            "YANDEX INPUT": {
                "exact_block_bytes": YANDEX_BLOCK_BYTES,
                "blocks_sent": self.yandex_blocks_sent,
                "trailing_silence_blocks": self.trailing_silence_blocks,
                "trailing_silence_bytes": self.trailing_silence_bytes,
                "trailing_silence_policy_ms": TRAILING_SILENCE_MS,
            },
            "RESPONSES": {
                "buffer_limit_bytes": RESPONSE_MAX_BYTES,
                "responses_dropped": self.responses_dropped,
                "responses": [response.summary() for response in self.responses.values()],
            },
            "SRS TX": {
                "transmissions": self.tx_transmissions,
                "frames": self.tx_frames,
                "final_padding_samples": self.final_padding_samples,
                "packet_id_next": self._packet_id,
                "jitter": list(self.tx_jitter_reports),
            },
            "SHUTDOWN": {
                "stop_requested": self.stop_event.is_set(),
                "network_thread_alive": self.thread.is_alive() if self.thread else False,
                "tx_thread_alive": self.tx_thread.is_alive() if self.tx_thread else False,
                "errors": list(self.errors),
            },
            "EVENT TIMELINE": list(self.timeline),
        }
        return sanitize_value(report, self.config.api_key)  # type: ignore[return-value]

    def diagnostic_text(self) -> str:
        return format_diagnostic_report(self.report(), self.config.api_key)
