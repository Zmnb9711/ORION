"""Production Yandex Realtime plus SRS Radio composition for ORION Core."""

from __future__ import annotations

import asyncio
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

from pydantic import BaseModel, Field, SecretStr

from orion.realtime_audio_transport import RealtimePcmFormat
from orion.srs_diagnostics import SrsTransportDiagnostics, sanitize_srs_error
from orion.srs_opus import OPUS_FRAME_BYTES, OpusDecoder, OpusEncoder
from orion.srs_protocol import (
    AM,
    Frequency,
    SrsProtocolError,
    VoicePacket,
    decode_voice_packet,
    encode_voice_packet,
)
from orion.srs_radio_transport import SrsRadioConfig, SrsRadioTransport, SrsState
from orion.srs_resampler import StreamingPcm16Resampler, make_rx_resampler, make_tx_resampler
from orion.srs_transmission import PacketDecision, TransmissionTracker, TxPacer, split_tx_pcm
from orion.yandex_live_diagnostics import YandexLiveDiagnostics
from orion.yandex_realtime_provider import YANDEX_INPUT_RATE, sanitize_yandex_error
from orion.yandex_realtime_session import YandexRealtimeSession

YANDEX_BLOCK_FRAMES = 882
YANDEX_BLOCK_BYTES = YANDEX_BLOCK_FRAMES * 2
TRAILING_SILENCE_MS = 400
TRAILING_SILENCE_BLOCKS = TRAILING_SILENCE_MS // 20
RESPONSE_MAX_SECONDS = 30
RESPONSE_MAX_BYTES = YANDEX_INPUT_RATE * 2 * RESPONSE_MAX_SECONDS
MAX_RESPONSE_STATES = 4
SHUTDOWN_TIMEOUT_SECONDS = 6.0


class YandexSrsState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    STREAMING = "streaming"
    ERROR = "error"


class YandexSrsStartRequest(BaseModel):
    api_key: str = Field(min_length=1, repr=False)
    folder_id: str = Field(min_length=1)
    host: str = "127.0.0.1"
    port: int = Field(default=5002, ge=1, le=65_535)
    bot_name: str = Field(default="ORION SRS", min_length=1, max_length=80)
    frequency_hz: float = Field(default=251_000_000.0, gt=0)
    modulation: int = AM
    eam_password: SecretStr


class YandexSrsStatus(BaseModel):
    state: YandexSrsState = YandexSrsState.STOPPED
    phase: str = "idle"
    message: str = "Yandex SRS voice is stopped"
    session_id: str | None = None
    server_version: str | None = None
    coalition: int | None = None
    frequency_hz: float = 251_000_000.0
    modulation: int = AM
    radio_registered: bool = False
    udp_registered: bool = False
    input_chunks: int = 0
    output_chunks: int = 0
    udp_packets_received: int = 0
    udp_packets_sent: int = 0
    decoded_samples: int = 0
    resampled_rx_samples: int = 0
    transmissions_started: int = 0
    transmissions_completed: int = 0
    tx_transmissions: int = 0
    tx_frames: int = 0
    malformed_packets: int = 0
    opus_decode_errors: int = 0
    last_error: str | None = None


@dataclass(slots=True)
class _ResponseState:
    response_id: str
    pcm: bytearray = field(default_factory=bytearray)
    audio_done: bool = False
    response_done: bool = False
    status: str = ""
    dropped: bool = False
    queued: bool = False


@dataclass(frozen=True, slots=True)
class _PreparedResponse:
    response_id: str
    pcm44: bytes


class SrsYandexPcmEndpoint:
    """Provider-native PCM endpoint backed by one SRS radio transport."""

    transport_id = "srs"
    pcm_format = RealtimePcmFormat()

    def __init__(
        self,
        config: SrsRadioConfig,
        stop_event: threading.Event,
        diagnostics: SrsTransportDiagnostics,
        status_callback: Callable[..., None],
        *,
        radio_factory: Callable[..., SrsRadioTransport] = SrsRadioTransport,
        decoder_factory: Callable[[], OpusDecoder] = OpusDecoder,
        encoder_factory: Callable[[], OpusEncoder] = OpusEncoder,
        rx_resampler_factory: Callable[[], StreamingPcm16Resampler] = make_rx_resampler,
        tx_resampler_factory: Callable[[], StreamingPcm16Resampler] = make_tx_resampler,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.stop_event = stop_event
        self.diagnostics = diagnostics
        self._status = status_callback
        self.clock = clock
        self.decoder = decoder_factory()
        self.encoder = encoder_factory()
        self.rx_resampler = rx_resampler_factory()
        self.tx_resampler = tx_resampler_factory()
        self.radio = radio_factory(config, self._on_radio_datagram, self._on_radio_event)
        self.tracker = TransmissionTracker(
            self.radio.client_guid,
            config.frequency_hz,
            config.modulation,
        )
        self.input_queue: queue.Queue[bytes] = queue.Queue(maxsize=250)
        self.tx_queue: queue.Queue[_PreparedResponse | None] = queue.Queue(maxsize=1)
        self.responses: dict[str, _ResponseState] = {}
        self.rx_accumulator = bytearray()
        self.packet_id = 1
        self.decoded_samples = 0
        self.resampled_rx_samples = 0
        self.malformed_packets = 0
        self.opus_decode_errors = 0
        self.tx_transmissions = 0
        self.tx_frames = 0
        self._lock = threading.RLock()
        self._started = False
        self._failure: BaseException | None = None
        self._rx_end_injected_at: float | None = None
        self._boundary_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None

    def connect_radio(self) -> None:
        self.radio.connect()
        if self.radio.state is not SrsState.READY:
            raise RuntimeError("SRS transport did not reach READY")
        self._status(
            phase="provider_connecting",
            server_version=self.radio.server_version,
            coalition=self.radio.coalition,
            radio_registered=self.radio.radio_registered,
            udp_registered=self.radio.udp_registered,
        )

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._boundary_thread = threading.Thread(
            target=self._boundary_worker,
            name="orion-srs-boundary",
            daemon=True,
        )
        self._tx_thread = threading.Thread(
            target=self._tx_worker,
            name="orion-srs-tx",
            daemon=True,
        )
        self._boundary_thread.start()
        self._tx_thread.start()

    def _on_radio_event(self, event: str, fields: dict[str, object]) -> None:
        safe = {key: value for key, value in fields.items() if "guid" not in key.casefold()}
        self.diagnostics.record(event, **safe)
        if event != "srs.state":
            return
        state = str(fields.get("value") or "")
        phase_by_state = {
            "CONNECTING_TCP": "srs_connecting",
            "SYNCING": "srs_connecting",
            "AUTHENTICATING_EAM": "srs_connecting",
            "REGISTERING_RADIO": "registering_radio",
            "RADIO_REGISTERED": "registering_udp",
            "REGISTERING_UDP": "registering_udp",
            "READY": "provider_connecting",
        }
        phase = phase_by_state.get(state)
        if phase is not None:
            self._status(phase=phase)

    def _on_radio_datagram(self, datagram: bytes) -> None:
        try:
            packet = decode_voice_packet(datagram)
        except SrsProtocolError as exc:
            self.malformed_packets += 1
            self.diagnostics.record("rx_malformed", error=str(exc), count=self.malformed_packets)
            return
        now = self.clock()
        with self._lock:
            decision = self.tracker.accept(packet, now)
            if decision is not PacketDecision.ACCEPTED:
                self.diagnostics.record("rx_dropped", decision=decision.value)
                return
            self._rx_end_injected_at = None
            try:
                decoded = self.decoder.decode(packet.audio)
            except Exception as exc:
                self.opus_decode_errors += 1
                self.diagnostics.record(
                    "opus_decode_error",
                    error=str(exc),
                    count=self.opus_decode_errors,
                )
                return
            self.decoded_samples += len(decoded) // 2
            resampled = self.rx_resampler.process(decoded)
            self.resampled_rx_samples += len(resampled) // 2
            self.rx_accumulator.extend(resampled)
            while len(self.rx_accumulator) >= YANDEX_BLOCK_BYTES:
                block = bytes(self.rx_accumulator[:YANDEX_BLOCK_BYTES])
                del self.rx_accumulator[:YANDEX_BLOCK_BYTES]
                if not self._enqueue_input(block):
                    return
                self._status(input_chunks_delta=1)
            counters = self.tracker.counters
            self._status(
                udp_packets_received=self.radio.udp_packets_received,
                decoded_samples=self.decoded_samples,
                resampled_rx_samples=self.resampled_rx_samples,
                transmissions_started=counters.transmissions_started,
                transmissions_completed=counters.transmissions_completed,
                malformed_packets=self.malformed_packets,
                opus_decode_errors=self.opus_decode_errors,
            )

    def _boundary_worker(self) -> None:
        while not self.stop_event.wait(0.02):
            now = self.clock()
            with self._lock:
                last_packet_at = self.tracker.last_human_packet_at
                completed = self.tracker.expire(now)
                if completed is None or last_packet_at is None:
                    continue
                if self._rx_end_injected_at == last_packet_at:
                    continue
                if self.rx_accumulator:
                    self.rx_accumulator.extend(bytes(YANDEX_BLOCK_BYTES - len(self.rx_accumulator)))
                    if not self._enqueue_input(bytes(self.rx_accumulator)):
                        return
                    self.rx_accumulator.clear()
                    self._status(input_chunks_delta=1)
                silence = bytes(YANDEX_BLOCK_BYTES)
                for _ in range(TRAILING_SILENCE_BLOCKS):
                    if not self._enqueue_input(silence):
                        return
                    self._status(input_chunks_delta=1)
                self._rx_end_injected_at = last_packet_at
                self._status(
                    transmissions_completed=self.tracker.counters.transmissions_completed
                )
                self.diagnostics.record(
                    "rx_transmission_completed",
                    trailing_silence_ms=TRAILING_SILENCE_MS,
                )

    def read_input(self, timeout: float = 0.1) -> bytes | None:
        try:
            return self.input_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _enqueue_input(self, block: bytes) -> bool:
        try:
            self.input_queue.put_nowait(block)
            return True
        except queue.Full:
            self._set_failure(RuntimeError("SRS provider input queue exceeded its hard bound"))
            return False

    def _set_failure(self, failure: BaseException) -> None:
        with self._lock:
            if self._failure is None:
                self._failure = failure
                self.diagnostics.record(
                    "endpoint_error",
                    error_type=type(failure).__name__,
                    error=str(failure),
                )
        self.stop_event.set()

    def failure(self) -> BaseException | None:
        with self._lock:
            failure = self._failure
        if failure is not None:
            return failure
        if self.radio.state is SrsState.ERROR:
            return ConnectionError("SRS transport failed during the Yandex session")
        return None

    def input_speech_started(self) -> None:
        self.diagnostics.record("provider_speech_started")

    def response_started(self, response_id: str) -> None:
        with self._lock:
            self._response(response_id, replace=True)

    def _response(self, response_id: str, *, replace: bool = False) -> _ResponseState:
        current = self.responses.get(response_id)
        if current is not None and not replace:
            return current
        if current is not None:
            current.pcm.clear()
        while len(self.responses) >= MAX_RESPONSE_STATES and response_id not in self.responses:
            oldest_id = next(iter(self.responses))
            oldest = self.responses.pop(oldest_id)
            oldest.pcm.clear()
            oldest.dropped = True
        response = _ResponseState(response_id)
        self.responses[response_id] = response
        return response

    def response_audio(self, response_id: str, pcm16le: bytes) -> None:
        if len(pcm16le) % 2:
            raise ValueError("Yandex response PCM is not aligned to int16 samples")
        with self._lock:
            response = self._response(response_id)
            if response.dropped:
                return
            if len(response.pcm) + len(pcm16le) > RESPONSE_MAX_BYTES:
                response.pcm.clear()
                response.dropped = True
                self.diagnostics.record(
                    "response_buffer_limit",
                    response_id=response_id,
                    limit_bytes=RESPONSE_MAX_BYTES,
                )
                return
            response.pcm.extend(pcm16le)

    def response_audio_done(self, response_id: str) -> None:
        with self._lock:
            response = self._response(response_id)
            response.audio_done = True
            self._maybe_queue(response)

    def response_done(self, response_id: str, status: str) -> None:
        with self._lock:
            response = self._response(response_id)
            response.response_done = True
            response.status = status
            if status != "completed":
                response.dropped = True
                response.pcm.clear()
            self._maybe_queue(response)

    def _maybe_queue(self, response: _ResponseState) -> None:
        if (
            response.queued
            or response.dropped
            or not response.audio_done
            or not response.response_done
            or response.status != "completed"
            or not response.pcm
        ):
            return
        try:
            self.tx_queue.put_nowait(_PreparedResponse(response.response_id, bytes(response.pcm)))
        except queue.Full:
            response.dropped = True
            response.pcm.clear()
            self.diagnostics.record("response_queue_full", response_id=response.response_id)
            return
        response.queued = True
        response.pcm.clear()

    def _tx_worker(self) -> None:
        pacer = TxPacer(clock=self.clock)
        while not self.stop_event.is_set():
            try:
                prepared = self.tx_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if prepared is None:
                return
            while not self.stop_event.wait(0.01):
                with self._lock:
                    if self.tracker.channel_clear(self.clock()):
                        self.tracker.bot_tx_active = True
                        break
            if self.stop_event.is_set():
                return
            try:
                pcm16 = self.tx_resampler.process(prepared.pcm44, end_of_input=True)
                frames, padding = split_tx_pcm(pcm16, OPUS_FRAME_BYTES)
                encoded_frames = tuple(self.encoder.encode(frame) for frame in frames)

                def send_frame(opus: bytes, _sent_at: float) -> None:
                    packet = VoicePacket(
                        audio=opus,
                        frequencies=(Frequency(self.config.frequency_hz, self.config.modulation),),
                        unit_id=self.config.unit_id,
                        packet_id=self.packet_id,
                        retransmission_count=0,
                        original_client_guid=self.radio.client_guid,
                        current_sender_guid=self.radio.client_guid,
                    )
                    self.radio.send_voice(encode_voice_packet(packet))
                    self.packet_id += 1

                report = pacer.send(encoded_frames, send_frame, self.stop_event)
                self.tx_transmissions += 1
                self.tx_frames += report.sent_frames
                self._status(
                    output_chunks_delta=report.sent_frames,
                    tx_transmissions=self.tx_transmissions,
                    tx_frames=self.tx_frames,
                    udp_packets_sent=self.radio.udp_packets_sent,
                )
                self.diagnostics.record(
                    "tx_completed",
                    frames=report.sent_frames,
                    final_padding_samples=padding,
                    median_jitter_ms=report.median_jitter_ms,
                    max_jitter_ms=report.max_jitter_ms,
                    cumulative_drift_ms=report.cumulative_drift_ms,
                )
            except Exception as exc:
                if not self.stop_event.is_set():
                    self._set_failure(exc)
            finally:
                with self._lock:
                    self.tracker.bot_tx_active = False
                self.tx_resampler.reset()

    def stop(self) -> None:
        self.stop_event.set()
        try:
            self.tx_queue.put_nowait(None)
        except queue.Full:
            try:
                self.tx_queue.get_nowait()
            except queue.Empty:
                pass
            self.tx_queue.put_nowait(None)
        self.radio.close()
        for worker in (self._boundary_thread, self._tx_thread):
            if worker is not None and worker is not threading.current_thread() and worker.is_alive():
                worker.join(2.0)
        self.decoder.close()
        self.encoder.close()
        with self._lock:
            for response in self.responses.values():
                response.pcm.clear()
                response.dropped = True


class YandexSrsLiveService:
    provider_id = "yandex"
    transport_id = "srs"

    def __init__(
        self,
        *,
        endpoint_factory: Callable[..., SrsYandexPcmEndpoint] = SrsYandexPcmEndpoint,
    ) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = YandexSrsStatus()
        self._endpoint_factory = endpoint_factory

    def status(self) -> YandexSrsStatus:
        with self._lock:
            return self._status.model_copy(deep=True)

    def _set(self, **changes: object) -> None:
        with self._lock:
            payload = self._status.model_dump()
            raw_input_delta = changes.pop("input_chunks_delta", 0)
            raw_output_delta = changes.pop("output_chunks_delta", 0)
            input_delta = raw_input_delta if isinstance(raw_input_delta, int) else 0
            output_delta = raw_output_delta if isinstance(raw_output_delta, int) else 0
            payload.update(changes)
            payload["input_chunks"] = int(payload["input_chunks"]) + input_delta
            payload["output_chunks"] = int(payload["output_chunks"]) + output_delta
            self._status = YandexSrsStatus.model_validate(payload)

    def start(self, request: YandexSrsStartRequest) -> YandexSrsStatus:
        if request.modulation != AM:
            raise ValueError("SRS Radio v0.1 supports AM only")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise ValueError("Yandex SRS voice is already running")
            self._stop = threading.Event()
            session_id = uuid.uuid4().hex
            self._status = YandexSrsStatus(
                state=YandexSrsState.STARTING,
                phase="srs_connecting",
                message="Starting Yandex SRS voice",
                session_id=session_id,
                frequency_hz=request.frequency_hz,
                modulation=request.modulation,
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(request, session_id, self._stop),
                name="orion-yandex-srs-live",
                daemon=True,
            )
            self._thread.start()
            return self._status.model_copy(deep=True)

    def _run(
        self,
        request: YandexSrsStartRequest,
        session_id: str,
        stop_event: threading.Event,
    ) -> None:
        api_key = request.api_key
        eam_password = request.eam_password.get_secret_value()
        srs_diagnostics = SrsTransportDiagnostics(
            session_id,
            secrets=(api_key, eam_password),
        )
        yandex_diagnostics = YandexLiveDiagnostics(session_id, api_key)
        endpoint: SrsYandexPcmEndpoint | None = None
        try:
            config = SrsRadioConfig(
                host=request.host,
                port=request.port,
                bot_name=request.bot_name,
                eam_password=eam_password,
                frequency_hz=request.frequency_hz,
                modulation=request.modulation,
            )
            endpoint = self._endpoint_factory(
                config,
                stop_event,
                srs_diagnostics,
                self._set,
            )
            endpoint.connect_radio()

            def streaming() -> None:
                self._set(
                    state=YandexSrsState.STREAMING,
                    phase="listening",
                    message="Yandex SRS voice is running",
                )

            asyncio.run(
                YandexRealtimeSession(
                    api_key,
                    request.folder_id,
                    endpoint,
                    stop_event,
                    yandex_diagnostics,
                    on_streaming=streaming,
                ).run()
            )
        except Exception as exc:
            safe = sanitize_yandex_error(
                sanitize_srs_error(exc, api_key, eam_password),
                api_key,
            )
            srs_diagnostics.record("session_error", error_type=type(exc).__name__, error=safe)
            self._set(
                state=YandexSrsState.ERROR,
                phase="idle",
                message=f"{type(exc).__name__}: {safe}",
                last_error=safe,
            )
        finally:
            stop_event.set()
            if endpoint is not None:
                endpoint.stop()
            with self._lock:
                if self._status.state is not YandexSrsState.ERROR:
                    self._status.state = YandexSrsState.STOPPED
                    self._status.phase = "idle"
                    self._status.message = "Yandex SRS voice stopped"

    def stop(self) -> YandexSrsStatus:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(SHUTDOWN_TIMEOUT_SECONDS)
        with self._lock:
            if thread is not None and thread.is_alive():
                self._status.state = YandexSrsState.ERROR
                self._status.message = "Yandex SRS shutdown exceeded its bound"
                self._status.last_error = self._status.message
            else:
                self._status.state = YandexSrsState.STOPPED
                self._status.phase = "idle"
                self._status.message = "Yandex SRS voice stopped"
            return self._status.model_copy(deep=True)


yandex_srs_live = YandexSrsLiveService()
