"""Production Yandex Realtime plus SRS Radio composition for ORION Core."""

from __future__ import annotations

import asyncio
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable

from pydantic import BaseModel, Field, SecretStr

from orion.communication_contracts import CommunicationDomain, CommunicationPriority
from orion.radio_contracts import (
    FinalizedPcmAudio,
    RadioContext,
    RadioEntityRef,
    RadioFailureCode,
    RadioTransmissionRequest,
    RadioTransmissionState,
)
from orion.radio_router import RadioRouter
from orion.realtime_audio_transport import (
    RealtimeInputTransmissionCompleted,
    RealtimeInputTransmissionStarted,
    RealtimePcmFormat,
)
from orion.srs_diagnostics import SrsTransportDiagnostics, sanitize_srs_error
from orion.srs_opus import OPUS_FRAME_BYTES, OpusDecoder, OpusEncoder
from orion.srs_protocol import (
    AM,
    Frequency,
    SRS_EXTERNAL_AUDIO_RADIO_INDEX,
    SrsProtocolError,
    VoicePacket,
    decode_voice_packet,
    encode_voice_packet,
)
from orion.srs_radio_transport import SrsRadioConfig, SrsRadioTransport, SrsState
from orion.srs_radio_adapter import (
    SRS_ADAPTER_ID,
    SrsAdapterRuntime,
    SrsRadioTransportAdapter,
    SrsTxCompletion,
    radio_modulation_from_srs,
)
from orion.srs_resampler import (
    StreamingPcm16Resampler,
    make_rx_resampler,
    make_tx_resampler,
)
from orion.srs_transmission import (
    PacketDecision,
    RX_END_GAP_SECONDS,
    TX_GUARD_SECONDS,
    TransmissionTracker,
    TxPacer,
    split_tx_pcm,
)
from orion.srs_tx_state import (
    SrsTxStateListener,
    SrsTxStateListenerStatus,
    SrsTxStateSnapshot,
)
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
SRS_DECODE_RATE_HZ = 16_000
SRS_TX_CONFIRM_TIMEOUT_SECONDS = 1.0


class YandexSrsState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    STREAMING = "streaming"
    ERROR = "error"


class RadioSttProvider(StrEnum):
    YANDEX_REALTIME = "yandex_realtime"
    SPEECHKIT_V3 = "speechkit_v3"


class YandexSrsStartRequest(BaseModel):
    api_key: str = Field(min_length=1, repr=False)
    folder_id: str = Field(min_length=1)
    host: str = "127.0.0.1"
    port: int = Field(default=5002, ge=1, le=65_535)
    bot_name: str = Field(default="ORION SRS", min_length=1, max_length=80)
    frequency_hz: float = Field(default=251_000_000.0, gt=0)
    modulation: int = AM
    eam_password: SecretStr
    radio_stt_provider: RadioSttProvider = RadioSttProvider.YANDEX_REALTIME


class YandexSrsStatus(BaseModel):
    state: YandexSrsState = YandexSrsState.STOPPED
    phase: str = "idle"
    message: str = "Yandex SRS voice is stopped"
    session_id: str | None = None
    server_version: str | None = None
    coalition: int | None = None
    frequency_hz: float = 251_000_000.0
    modulation: int = AM
    radio_stt_provider: RadioSttProvider = RadioSttProvider.YANDEX_REALTIME
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
    srs_tx_state_status: str = "not_required"
    srs_tx_state_is_sending: bool | None = None
    srs_tx_state_sending_on: int | None = None
    srs_tx_state_snapshot_age_ms: float | None = None
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


@dataclass(slots=True)
class _RxTurnEvidence:
    transmission_id: str
    first_accepted_packet_timestamp: str
    last_accepted_packet_timestamp: str
    first_packet_id: int
    last_packet_id: int
    accepted_packet_count: int = 0
    sequence_gap_count: int = 0
    decode_error_count: int = 0
    decoded_pcm_bytes: int = 0
    padding_bytes: int = 0
    framed_pcm_bytes: int = 0


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
        provider_input_rate_hz: int = YANDEX_INPUT_RATE,
        authoritative_tx_state: bool = False,
        tx_state_listener_factory: Callable[..., SrsTxStateListener] = (
            SrsTxStateListener
        ),
    ) -> None:
        if provider_input_rate_hz not in {SRS_DECODE_RATE_HZ, YANDEX_INPUT_RATE}:
            raise ValueError("Unsupported SRS provider PCM rate")
        self.config = config
        self.stop_event = stop_event
        self.diagnostics = diagnostics
        self._status = status_callback
        self.clock = clock
        self._authoritative_tx_state = authoritative_tx_state
        self._expected_sending_on = SRS_EXTERNAL_AUDIO_RADIO_INDEX
        self.pcm_format = RealtimePcmFormat(sample_rate=provider_input_rate_hz)
        self._input_block_frames = provider_input_rate_hz // 50
        self._input_block_bytes = self._input_block_frames * 2
        self._trailing_silence_blocks = (
            TRAILING_SILENCE_BLOCKS
            if provider_input_rate_hz == YANDEX_INPUT_RATE
            else 0
        )
        self.decoder = decoder_factory()
        self.encoder = encoder_factory()
        self.rx_resampler = rx_resampler_factory()
        self.tx_resampler = tx_resampler_factory()
        self.radio = radio_factory(
            config, self._on_radio_datagram, self._on_radio_event
        )
        self.tracker = TransmissionTracker(
            self.radio.client_guid,
            config.frequency_hz,
            config.modulation,
        )
        self.input_queue: queue.Queue[
            bytes
            | RealtimeInputTransmissionStarted
            | RealtimeInputTransmissionCompleted
        ] = queue.Queue(maxsize=250)
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
        self._active_rx_transmission_id: str | None = None
        self._rx_turn_evidence: _RxTurnEvidence | None = None
        self._boundary_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None
        self._probe_lock = threading.Lock()
        self._probe_tx_started: dict[str, tuple[threading.Event, float | None]] = {}
        self._probe_tx_completed: dict[str, tuple[threading.Event, float | None]] = {}
        self._probe_tx_results: dict[str, tuple[int, float]] = {}
        self.radio_adapter: SrsRadioTransportAdapter | None = None
        self.radio_router: RadioRouter | None = None
        self._stop_lock = threading.Lock()
        self._resources_stopped = False
        self._provider_output_suppressed = False
        self._tx_state_latest: SrsTxStateSnapshot | None = None
        self._tx_state_confirmed_transmission_id: str | None = None
        self._tx_state_confirmed_sending_on: int | None = None
        self._tx_state_candidate_started_at: float | None = None
        self._tx_state_started_timestamp: str | None = None
        self._last_authoritative_tx_end_at: float | None = None
        self._tx_state_listener = (
            tx_state_listener_factory(
                stop_event,
                self._on_tx_state_snapshot,
                self._on_tx_state_status,
                lambda event, fields: self.diagnostics.record(event, **fields),
                clock=clock,
            )
            if authoritative_tx_state
            else None
        )

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
        if self._tx_state_listener is not None:
            self._status(
                phase="srs_tx_state_connecting",
                srs_tx_state_status=SrsTxStateListenerStatus.WAITING.value,
            )
            self._tx_state_listener.start()

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
        self.radio_adapter = SrsRadioTransportAdapter(
            self,
            diagnostic=lambda event, fields: self.diagnostics.record(event, **fields),
        )
        self.radio_router = RadioRouter(
            default_transport_id=SRS_ADAPTER_ID,
            queue_capacity=1,
        )
        self.radio_router.register_adapter(self.radio_adapter)
        self.radio_router.start()

    def _on_radio_event(self, event: str, fields: dict[str, object]) -> None:
        safe = {
            key: value for key, value in fields.items() if "guid" not in key.casefold()
        }
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

    def _on_tx_state_status(
        self,
        status: SrsTxStateListenerStatus,
        snapshot_age_ms: float | None,
    ) -> None:
        message = (
            "SpeechKit v3 SRS voice is running"
            if self._started
            else "Starting SpeechKit v3 SRS voice"
        )
        self._status(
            srs_tx_state_status=status.value,
            srs_tx_state_snapshot_age_ms=snapshot_age_ms,
            message=f"{message} | SRS TX STATE: {status.value.upper()}",
        )
        if status is not SrsTxStateListenerStatus.STALE:
            return
        with self._lock:
            active = self._active_rx_transmission_id is not None
        if active:
            self._set_failure(
                RuntimeError(
                    "SRS TX-state stream became stale during an active radio turn"
                )
            )

    def _on_tx_state_snapshot(
        self,
        snapshot: SrsTxStateSnapshot,
        previous: SrsTxStateSnapshot | None,
    ) -> None:
        with self._lock:
            self._tx_state_latest = snapshot
            self._status(
                srs_tx_state_status=SrsTxStateListenerStatus.READY.value,
                srs_tx_state_is_sending=snapshot.is_sending,
                srs_tx_state_sending_on=snapshot.sending_on,
                srs_tx_state_snapshot_age_ms=0.0,
            )
            active_id = self._active_rx_transmission_id
            start_observed = snapshot.is_sending and (
                previous is None or not previous.is_sending
            )
            end_observed = (
                not snapshot.is_sending
                and previous is not None
                and previous.is_sending
            )
            if start_observed:
                if snapshot.sending_on == self._expected_sending_on:
                    self._tx_state_started_timestamp = snapshot.received_timestamp
                self.diagnostics.record(
                    "srs_tx_started",
                    source="udp_7082",
                    is_sending=True,
                    sending_on=snapshot.sending_on,
                    is_encrypted=snapshot.is_encrypted,
                    active_orion_turn_id=active_id,
                    transition_authoritative=previous is not None,
                    snapshot_timestamp=snapshot.received_timestamp,
                )
            if snapshot.is_sending and active_id is not None:
                if snapshot.sending_on == self._expected_sending_on:
                    self._confirm_tx_state(snapshot)
                elif self._tx_state_confirmed_transmission_id == active_id:
                    self._set_failure(
                        RuntimeError(
                            "SRS TX-state radio ownership changed during an active turn"
                        )
                    )
                    return
            if not end_observed or previous is None:
                return
            if (
                active_id is None
                or self._tx_state_confirmed_transmission_id != active_id
                or self._tx_state_confirmed_sending_on != previous.sending_on
                or previous.sending_on != self._expected_sending_on
            ):
                self.diagnostics.record(
                    "srs_tx_ended",
                    source="udp_7082",
                    sending_on=previous.sending_on,
                    active_orion_turn_id=active_id,
                    transition_authoritative=True,
                    eou_triggered_by_7082=False,
                    reason="uncorrelated_tx_state",
                    snapshot_timestamp=snapshot.received_timestamp,
                )
                if previous.sending_on == self._expected_sending_on:
                    self._tx_state_started_timestamp = None
                return
            self._complete_authoritative_turn(snapshot, previous.sending_on)

    def _confirm_tx_state(self, snapshot: SrsTxStateSnapshot) -> None:
        transmission_id = self._active_rx_transmission_id
        if transmission_id is None:
            return
        if self._tx_state_confirmed_transmission_id == transmission_id:
            return
        self._tx_state_confirmed_transmission_id = transmission_id
        self._tx_state_confirmed_sending_on = snapshot.sending_on
        if self._tx_state_started_timestamp is None:
            self._tx_state_started_timestamp = snapshot.received_timestamp
        self.diagnostics.record(
            "srs_tx_state_correlated",
            active_orion_turn_id=transmission_id,
            sending_on=snapshot.sending_on,
            is_encrypted=snapshot.is_encrypted,
            tx_state_confirmed=True,
            snapshot_timestamp=snapshot.received_timestamp,
        )

    def _on_radio_datagram(self, datagram: bytes) -> None:
        try:
            packet = decode_voice_packet(datagram)
        except SrsProtocolError as exc:
            self.malformed_packets += 1
            self.diagnostics.record(
                "rx_malformed", error=str(exc), count=self.malformed_packets
            )
            return
        now = self.clock()
        with self._lock:
            if self._authoritative_tx_state and (
                self._tx_state_listener is None
                or self._tx_state_listener.status
                is not SrsTxStateListenerStatus.READY
            ):
                self._set_failure(
                    RuntimeError(
                        "SRS voice arrived without a healthy authoritative TX-state stream"
                    )
                )
                return
            previous_sequence_gaps = self.tracker.counters.sequence_gaps
            decision = self.tracker.accept(
                packet,
                now,
                expire_on_quiescence=not self._authoritative_tx_state,
            )
            if decision is not PacketDecision.ACCEPTED:
                self.diagnostics.record("rx_dropped", decision=decision.value)
                return
            accepted_at = datetime.now(UTC).isoformat(timespec="milliseconds")
            sequence_gap_delta = (
                self.tracker.counters.sequence_gaps - previous_sequence_gaps
            )
            if self._rx_turn_evidence is None:
                transmission_id = (
                    f"srs-ptt-{self.tracker.counters.transmissions_started:06d}"
                )
                self._rx_turn_evidence = _RxTurnEvidence(
                    transmission_id=transmission_id,
                    first_accepted_packet_timestamp=accepted_at,
                    last_accepted_packet_timestamp=accepted_at,
                    first_packet_id=packet.packet_id,
                    last_packet_id=packet.packet_id,
                )
            turn_evidence = self._rx_turn_evidence
            turn_evidence.last_accepted_packet_timestamp = accepted_at
            turn_evidence.last_packet_id = packet.packet_id
            turn_evidence.accepted_packet_count += 1
            turn_evidence.sequence_gap_count += sequence_gap_delta
            self._rx_end_injected_at = None
            try:
                decoded = self.decoder.decode(packet.audio)
            except Exception as exc:
                self.opus_decode_errors += 1
                turn_evidence.decode_error_count += 1
                self.diagnostics.record(
                    "opus_decode_error",
                    error=str(exc),
                    count=self.opus_decode_errors,
                )
                return
            turn_evidence.decoded_pcm_bytes += len(decoded)
            self.decoded_samples += len(decoded) // 2
            if self.pcm_format.sample_rate == SRS_DECODE_RATE_HZ:
                provider_pcm = decoded
            else:
                provider_pcm = self.rx_resampler.process(decoded)
                self.resampled_rx_samples += len(provider_pcm) // 2
            if self._active_rx_transmission_id is None:
                self._active_rx_transmission_id = turn_evidence.transmission_id
                self._tx_state_candidate_started_at = now
                if not self._enqueue_input(
                    RealtimeInputTransmissionStarted(
                        transmission_id=self._active_rx_transmission_id
                    )
                ):
                    return
                self.diagnostics.record(
                    "rx_transmission_started",
                    physical_transmission_id=self._active_rx_transmission_id,
                    boundary_source=(
                        "srs_tx_state"
                        if self._authoritative_tx_state
                        else "packet_quiescence"
                    ),
                )
                latest = self._tx_state_latest
                if (
                    self._authoritative_tx_state
                    and latest is not None
                    and latest.is_sending
                    and latest.sending_on == self._expected_sending_on
                ):
                    self._confirm_tx_state(latest)
            self.rx_accumulator.extend(provider_pcm)
            while len(self.rx_accumulator) >= self._input_block_bytes:
                block = bytes(self.rx_accumulator[: self._input_block_bytes])
                del self.rx_accumulator[: self._input_block_bytes]
                if not self._enqueue_input(block):
                    return
                turn_evidence.framed_pcm_bytes += len(block)
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

    def _flush_authoritative_rx_pcm(self) -> bool:
        if not self.rx_accumulator:
            return True
        padding_bytes = self._input_block_bytes - len(self.rx_accumulator)
        self.rx_accumulator.extend(bytes(padding_bytes))
        if not self._enqueue_input(bytes(self.rx_accumulator)):
            return False
        if self._rx_turn_evidence is not None:
            self._rx_turn_evidence.padding_bytes += padding_bytes
            self._rx_turn_evidence.framed_pcm_bytes += len(self.rx_accumulator)
        self.rx_accumulator.clear()
        self._status(input_chunks_delta=1)
        return True

    def _complete_authoritative_turn(
        self,
        snapshot: SrsTxStateSnapshot,
        sending_on: int,
    ) -> None:
        transmission_id = self._active_rx_transmission_id
        turn_evidence = self._rx_turn_evidence
        if transmission_id is None or turn_evidence is None:
            return
        if not self._flush_authoritative_rx_pcm():
            return
        if not self._enqueue_input(
            RealtimeInputTransmissionCompleted(
                transmission_id=transmission_id,
                boundary="srs_tx_state_end",
                first_accepted_packet_timestamp=(
                    turn_evidence.first_accepted_packet_timestamp
                ),
                last_accepted_packet_timestamp=(
                    turn_evidence.last_accepted_packet_timestamp
                ),
                accepted_packet_count=turn_evidence.accepted_packet_count,
                first_packet_id=turn_evidence.first_packet_id,
                last_packet_id=turn_evidence.last_packet_id,
                sequence_gap_count=turn_evidence.sequence_gap_count,
                decode_error_count=turn_evidence.decode_error_count,
                decoded_pcm_bytes=turn_evidence.decoded_pcm_bytes,
                padding_bytes=turn_evidence.padding_bytes,
                framed_pcm_bytes=turn_evidence.framed_pcm_bytes,
                srs_tx_started_timestamp=self._tx_state_started_timestamp,
                srs_tx_ended_timestamp=snapshot.received_timestamp,
                srs_tx_sending_on=sending_on,
                srs_tx_state_authoritative=True,
            )
        ):
            return
        self.tracker.complete_active()
        self._status(
            transmissions_completed=self.tracker.counters.transmissions_completed
        )
        self.diagnostics.record(
            "srs_tx_ended",
            source="udp_7082",
            is_sending=False,
            sending_on=sending_on,
            is_encrypted=snapshot.is_encrypted,
            active_orion_turn_id=transmission_id,
            transition_authoritative=True,
            eou_triggered_by_7082=True,
            boundary_marker_queued=True,
            snapshot_timestamp=snapshot.received_timestamp,
            last_voice_packet_timestamp=(
                turn_evidence.last_accepted_packet_timestamp
            ),
            accepted_packet_count=turn_evidence.accepted_packet_count,
            sequence_gap_count=turn_evidence.sequence_gap_count,
            decoded_pcm_bytes=turn_evidence.decoded_pcm_bytes,
            padding_bytes=turn_evidence.padding_bytes,
            framed_pcm_bytes=turn_evidence.framed_pcm_bytes,
        )
        self.diagnostics.record(
            "rx_transmission_completed",
            boundary_source="srs_tx_state",
            boundary_marker_queued=True,
            boundary_gap_ms=None,
            physical_transmission_id=transmission_id,
            trailing_silence_ms=0,
            first_accepted_packet_timestamp=(
                turn_evidence.first_accepted_packet_timestamp
            ),
            last_accepted_packet_timestamp=(
                turn_evidence.last_accepted_packet_timestamp
            ),
            accepted_packet_count=turn_evidence.accepted_packet_count,
            first_packet_id=turn_evidence.first_packet_id,
            last_packet_id=turn_evidence.last_packet_id,
            sequence_gap_count=turn_evidence.sequence_gap_count,
            decode_error_count=turn_evidence.decode_error_count,
            decoded_pcm_bytes=turn_evidence.decoded_pcm_bytes,
            padding_bytes=turn_evidence.padding_bytes,
            framed_pcm_bytes=turn_evidence.framed_pcm_bytes,
            srs_tx_started_timestamp=self._tx_state_started_timestamp,
            srs_tx_ended_timestamp=snapshot.received_timestamp,
            srs_tx_sending_on=sending_on,
            srs_tx_state_authoritative=True,
        )
        self._active_rx_transmission_id = None
        self._rx_turn_evidence = None
        self._rx_end_injected_at = self.tracker.last_human_packet_at
        self._tx_state_candidate_started_at = None
        self._tx_state_confirmed_transmission_id = None
        self._tx_state_confirmed_sending_on = None
        self._tx_state_started_timestamp = None
        self._last_authoritative_tx_end_at = snapshot.received_at

    def _channel_clear_for_tx(self, now: float) -> bool:
        if not self._authoritative_tx_state:
            return self.tracker.channel_clear(now)
        listener = self._tx_state_listener
        latest = self._tx_state_latest
        if (
            listener is None
            or listener.status is not SrsTxStateListenerStatus.READY
            or latest is None
            or latest.is_sending
            or self._active_rx_transmission_id is not None
            or self.tracker.active_origin_guid is not None
            or self.tracker.bot_tx_active
        ):
            return False
        return self._last_authoritative_tx_end_at is None or (
            now - self._last_authoritative_tx_end_at >= TX_GUARD_SECONDS
        )

    def _boundary_worker(self) -> None:
        while not self.stop_event.wait(0.02):
            now = self.clock()
            with self._lock:
                if self._authoritative_tx_state:
                    candidate_started = self._tx_state_candidate_started_at
                    active_id = self._active_rx_transmission_id
                    if (
                        active_id is not None
                        and self._tx_state_confirmed_transmission_id != active_id
                        and candidate_started is not None
                        and now - candidate_started
                        >= SRS_TX_CONFIRM_TIMEOUT_SECONDS
                    ):
                        self.diagnostics.record(
                            "srs_tx_state_stale",
                            reason="active_turn_not_confirmed",
                            active_orion_turn_id=active_id,
                            confirmation_timeout_ms=(
                                SRS_TX_CONFIRM_TIMEOUT_SECONDS * 1000
                            ),
                        )
                        self._set_failure(
                            RuntimeError(
                                "SRS TX-state did not confirm the active radio turn"
                            )
                        )
                    continue
                last_packet_at = self.tracker.last_human_packet_at
                completed = self.tracker.expire(now)
                if completed is None or last_packet_at is None:
                    continue
                if self._rx_end_injected_at == last_packet_at:
                    continue
                if self.rx_accumulator:
                    padding_bytes = self._input_block_bytes - len(self.rx_accumulator)
                    self.rx_accumulator.extend(bytes(padding_bytes))
                    if not self._enqueue_input(bytes(self.rx_accumulator)):
                        return
                    if self._rx_turn_evidence is not None:
                        self._rx_turn_evidence.padding_bytes += padding_bytes
                        self._rx_turn_evidence.framed_pcm_bytes += len(
                            self.rx_accumulator
                        )
                    self.rx_accumulator.clear()
                    self._status(input_chunks_delta=1)
                silence = bytes(self._input_block_bytes)
                for _ in range(self._trailing_silence_blocks):
                    if not self._enqueue_input(silence):
                        return
                    if self._rx_turn_evidence is not None:
                        self._rx_turn_evidence.framed_pcm_bytes += len(silence)
                    self._status(input_chunks_delta=1)
                transmission_id = self._active_rx_transmission_id
                if transmission_id is None:
                    self.diagnostics.record(
                        "rx_transmission_boundary_skipped",
                        reason="no_decoded_input",
                    )
                    self._rx_end_injected_at = last_packet_at
                    self._rx_turn_evidence = None
                    continue
                turn_evidence = self._rx_turn_evidence
                quiescence_completed_at = datetime.now(UTC).isoformat(
                    timespec="milliseconds"
                )
                if turn_evidence is None:
                    raise RuntimeError("SRS RX evidence state is missing at boundary")
                if not self._enqueue_input(
                    RealtimeInputTransmissionCompleted(
                        transmission_id=transmission_id,
                        first_accepted_packet_timestamp=(
                            turn_evidence.first_accepted_packet_timestamp
                        ),
                        last_accepted_packet_timestamp=(
                            turn_evidence.last_accepted_packet_timestamp
                        ),
                        accepted_packet_count=turn_evidence.accepted_packet_count,
                        first_packet_id=turn_evidence.first_packet_id,
                        last_packet_id=turn_evidence.last_packet_id,
                        sequence_gap_count=turn_evidence.sequence_gap_count,
                        decode_error_count=turn_evidence.decode_error_count,
                        decoded_pcm_bytes=turn_evidence.decoded_pcm_bytes,
                        padding_bytes=turn_evidence.padding_bytes,
                        framed_pcm_bytes=turn_evidence.framed_pcm_bytes,
                        packet_quiescence_completed_timestamp=(
                            quiescence_completed_at
                        ),
                        boundary_gap_ms=int(RX_END_GAP_SECONDS * 1000),
                    )
                ):
                    return
                self._active_rx_transmission_id = None
                self._rx_turn_evidence = None
                self._rx_end_injected_at = last_packet_at
                self._status(
                    transmissions_completed=self.tracker.counters.transmissions_completed
                )
                self.diagnostics.record(
                    "rx_transmission_completed",
                    boundary_marker_queued=True,
                    boundary_gap_ms=int(RX_END_GAP_SECONDS * 1000),
                    physical_transmission_id=transmission_id,
                    trailing_silence_ms=(
                        TRAILING_SILENCE_MS if self._trailing_silence_blocks else 0
                    ),
                    first_accepted_packet_timestamp=(
                        turn_evidence.first_accepted_packet_timestamp
                    ),
                    last_accepted_packet_timestamp=(
                        turn_evidence.last_accepted_packet_timestamp
                    ),
                    accepted_packet_count=turn_evidence.accepted_packet_count,
                    first_packet_id=turn_evidence.first_packet_id,
                    last_packet_id=turn_evidence.last_packet_id,
                    sequence_gap_count=turn_evidence.sequence_gap_count,
                    decode_error_count=turn_evidence.decode_error_count,
                    decoded_pcm_bytes=turn_evidence.decoded_pcm_bytes,
                    padding_bytes=turn_evidence.padding_bytes,
                    framed_pcm_bytes=turn_evidence.framed_pcm_bytes,
                    packet_quiescence_completed_timestamp=quiescence_completed_at,
                )

    def read_input(
        self, timeout: float = 0.1
    ) -> (
        bytes
        | RealtimeInputTransmissionStarted
        | RealtimeInputTransmissionCompleted
        | None
    ):
        try:
            return self.input_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _enqueue_input(
        self,
        block: bytes
        | RealtimeInputTransmissionStarted
        | RealtimeInputTransmissionCompleted,
    ) -> bool:
        try:
            self.input_queue.put_nowait(block)
            return True
        except queue.Full:
            self._set_failure(
                RuntimeError("SRS provider input queue exceeded its hard bound")
            )
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
            for marker, _timestamp in self._probe_tx_completed.values():
                marker.set()
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
        while (
            len(self.responses) >= MAX_RESPONSE_STATES
            and response_id not in self.responses
        ):
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
            if self._provider_output_suppressed:
                response.dropped = True
                response.pcm.clear()
                return
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
            self._provider_output_suppressed
            or
            response.queued
            or response.dropped
            or not response.audio_done
            or not response.response_done
            or response.status != "completed"
            or not response.pcm
        ):
            return
        try:
            self.tx_queue.put_nowait(
                _PreparedResponse(response.response_id, bytes(response.pcm))
            )
        except queue.Full:
            response.dropped = True
            response.pcm.clear()
            self.diagnostics.record(
                "response_queue_full", response_id=response.response_id
            )
            return
        response.queued = True
        response.pcm.clear()

    def set_provider_output_suppressed(self, suppressed: bool) -> None:
        """Bounded Live Golden gate; provider-generated PCM never reaches radio."""

        with self._lock:
            self._provider_output_suppressed = bool(suppressed)
            if suppressed:
                for response in self.responses.values():
                    response.pcm.clear()
                    response.dropped = True
        self.diagnostics.record(
            "provider_output_suppression_changed",
            status="enabled" if suppressed else "disabled",
        )

    def transmit_probe_audio(
        self,
        response_id: str,
        pcm44: bytes,
        timeout_s: float,
    ) -> dict[str, float | int]:
        """Route one hybrid-probe utterance through RadioRouter and the SRS adapter."""

        return self.transmit_finalized_audio(
            response_id,
            pcm44,
            timeout_s,
            source_domain=CommunicationDomain.GENERAL,
            priority=CommunicationPriority.IMPORTANT,
            entity_id="orion.srs.hybrid-probe",
        )

    def transmit_finalized_audio(
        self,
        response_id: str,
        pcm44: bytes,
        timeout_s: float,
        *,
        source_domain: CommunicationDomain,
        priority: CommunicationPriority,
        entity_id: str,
    ) -> dict[str, float | int]:
        """Route already-finalized PCM through the one production Router/adapter."""

        router = self.radio_router
        if router is None:
            raise RuntimeError("SRS RadioRouter is not started")
        runtime = self.srs_adapter_runtime()
        coalition = {1: "red", 2: "blue"}.get(runtime.coalition)
        request = RadioTransmissionRequest(
            context=RadioContext(
                tx_correlation_id=response_id,
                source_domain=source_domain,
                radio_entity=RadioEntityRef(
                    entity_id=entity_id,
                    operational_callsign=runtime.bot_name,
                    coalition=coalition,
                ),
                target_frequency_hz=runtime.frequency_hz,
                modulation=radio_modulation_from_srs(runtime.modulation),
                communication_priority=priority,
            ),
            audio=FinalizedPcmAudio(pcm=pcm44, sample_rate_hz=YANDEX_INPUT_RATE),
            transport_id=SRS_ADAPTER_ID,
            timeout_s=timeout_s,
        )
        submitted = router.submit(request)
        if not submitted.accepted:
            assert submitted.failure is not None
            raise RuntimeError(
                f"SRS RadioRouter rejected hybrid probe: {submitted.failure.code.value}"
            )
        snapshot = router.wait(response_id, timeout_s + 0.5)
        if snapshot is None or snapshot.state not in {
            RadioTransmissionState.COMPLETED,
            RadioTransmissionState.FAILED,
            RadioTransmissionState.CANCELLED,
        }:
            raise TimeoutError("Timed out waiting for generic SRS TX completion")
        if snapshot.state is not RadioTransmissionState.COMPLETED:
            failure = snapshot.failure
            if failure is not None and failure.code is RadioFailureCode.TX_TIMEOUT:
                raise TimeoutError("Timed out waiting for matching SRS tx_completed")
            code = failure.code.value if failure is not None else snapshot.state.value
            raise RuntimeError(f"SRS radio transmission failed: {code}")
        if snapshot.started_at is None or snapshot.completed_at is None:
            raise RuntimeError(
                "SRS adapter completed without correlated timing markers"
            )
        return {
            "queue_to_first_tx_ms": (
                snapshot.started_at - snapshot.enqueued_at
            ).total_seconds()
            * 1000,
            "queue_to_complete_ms": (
                snapshot.completed_at - snapshot.enqueued_at
            ).total_seconds()
            * 1000,
            "frame_count": snapshot.frame_count or 0,
            "duration_ms": snapshot.duration_ms or 0.0,
        }

    def srs_adapter_runtime(self) -> SrsAdapterRuntime:
        return SrsAdapterRuntime(
            state=self.radio.state,
            endpoint_started=self._started and not self._resources_stopped,
            radio_registered=self.radio.radio_registered,
            udp_registered=self.radio.udp_registered,
            frequency_hz=self.config.frequency_hz,
            modulation=self.config.modulation,
            bot_name=self.config.bot_name,
            coalition=self.radio.coalition,
            failed=self.failure() is not None,
        )

    def transmit_srs_pcm(
        self,
        tx_correlation_id: str,
        pcm44: bytes,
        timeout_s: float,
    ) -> SrsTxCompletion:
        """Use the field-proven single-slot TX worker and matching completion marker."""

        response_id = tx_correlation_id
        if not response_id or len(response_id) > 200:
            raise ValueError("Hybrid probe response ID is invalid")
        if not pcm44 or len(pcm44) % 2 or len(pcm44) > RESPONSE_MAX_BYTES:
            raise ValueError(
                "Hybrid probe PCM is empty, unaligned, or exceeds the response bound"
            )
        if timeout_s <= 0:
            raise ValueError("Hybrid probe TX timeout must be positive")
        with self._probe_lock:
            if self.failure() is not None or self.stop_event.is_set():
                raise RuntimeError("SRS endpoint is not available for hybrid probe TX")
            started_event = threading.Event()
            completed_event = threading.Event()
            with self._lock:
                if self.tracker.bot_tx_active or not self.tx_queue.empty():
                    raise RuntimeError(
                        "SRS TX is busy; hybrid probe did not enter the bounded queue"
                    )
                self._probe_tx_started[response_id] = (started_event, None)
                self._probe_tx_completed[response_id] = (completed_event, None)
                self._probe_tx_results.pop(response_id, None)
                queued_at = self.clock()
                try:
                    self.tx_queue.put_nowait(
                        _PreparedResponse(response_id, bytes(pcm44))
                    )
                except queue.Full as exc:
                    self._probe_tx_started.pop(response_id, None)
                    self._probe_tx_completed.pop(response_id, None)
                    self._probe_tx_results.pop(response_id, None)
                    raise RuntimeError(
                        "SRS TX queue is busy; hybrid probe was not queued"
                    ) from exc
            if not completed_event.wait(timeout_s):
                with self._lock:
                    self._probe_tx_started.pop(response_id, None)
                    self._probe_tx_completed.pop(response_id, None)
                    self._probe_tx_results.pop(response_id, None)
                raise TimeoutError("Timed out waiting for matching SRS tx_completed")
            with self._lock:
                started_at = self._probe_tx_started.pop(
                    response_id, (started_event, None)
                )[1]
                completed_at = self._probe_tx_completed.pop(
                    response_id, (completed_event, None)
                )[1]
                result = self._probe_tx_results.pop(response_id, None)
            if started_at is None or completed_at is None:
                raise RuntimeError(
                    "SRS probe TX completed without correlated timing markers"
                )
            if result is None:
                raise RuntimeError(
                    "SRS probe TX completed without a correlated frame result"
                )
            frame_count, duration_ms = result
            return SrsTxCompletion(
                queue_to_first_tx_ms=(started_at - queued_at) * 1000,
                queue_to_complete_ms=(completed_at - queued_at) * 1000,
                frame_count=frame_count,
                duration_ms=duration_ms,
            )

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
                    if self._channel_clear_for_tx(self.clock()):
                        self.tracker.bot_tx_active = True
                        break
            if self.stop_event.is_set():
                return
            try:
                response_id = prepared.response_id
                pcm16 = self.tx_resampler.process(prepared.pcm44, end_of_input=True)
                frames, padding = split_tx_pcm(pcm16, OPUS_FRAME_BYTES)
                encoded_frames = tuple(self.encoder.encode(frame) for frame in frames)
                tx_started = False

                def send_frame(opus: bytes, _sent_at: float) -> None:
                    nonlocal tx_started
                    packet = VoicePacket(
                        audio=opus,
                        frequencies=(
                            Frequency(self.config.frequency_hz, self.config.modulation),
                        ),
                        unit_id=self.config.unit_id,
                        packet_id=self.packet_id,
                        retransmission_count=0,
                        original_client_guid=self.radio.client_guid,
                        current_sender_guid=self.radio.client_guid,
                    )
                    self.radio.send_voice(encode_voice_packet(packet))
                    if not tx_started:
                        tx_started = True
                        with self._lock:
                            marker = self._probe_tx_started.get(response_id)
                            if marker is not None:
                                self._probe_tx_started[response_id] = (
                                    marker[0],
                                    self.clock(),
                                )
                                marker[0].set()
                        self.diagnostics.record(
                            "srs_tx_started",
                            response_id=response_id,
                            packet_id=self.packet_id,
                        )
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
                    response_id=response_id,
                    frames=report.sent_frames,
                    final_padding_samples=padding,
                    median_jitter_ms=report.median_jitter_ms,
                    max_jitter_ms=report.max_jitter_ms,
                    cumulative_drift_ms=report.cumulative_drift_ms,
                )
                with self._lock:
                    marker = self._probe_tx_completed.get(response_id)
                    if marker is not None:
                        completed_at = self.clock()
                        started_marker = self._probe_tx_started.get(response_id)
                        started_at = (
                            started_marker[1] if started_marker is not None else None
                        )
                        duration_ms = (
                            max(0.0, (completed_at - started_at) * 1000)
                            if started_at is not None
                            else 0.0
                        )
                        self._probe_tx_completed[response_id] = (
                            marker[0],
                            completed_at,
                        )
                        self._probe_tx_results[response_id] = (
                            report.sent_frames,
                            duration_ms,
                        )
                        marker[0].set()
            except Exception as exc:
                if not self.stop_event.is_set():
                    self._set_failure(exc)
            finally:
                with self._lock:
                    self.tracker.bot_tx_active = False
                self.tx_resampler.reset()

    def shutdown_srs_adapter(self, timeout_s: float) -> bool:
        return self._stop_transport_resources(timeout_s)

    def _stop_transport_resources(self, timeout_s: float = 2.0) -> bool:
        with self._stop_lock:
            if self._resources_stopped:
                return True
            deadline = time.monotonic() + max(0.01, timeout_s)
            self.stop_event.set()
            if self._tx_state_listener is not None:
                self._tx_state_listener.stop()
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
                if (
                    worker is not None
                    and worker is not threading.current_thread()
                    and worker.is_alive()
                ):
                    worker.join(max(0.0, deadline - time.monotonic()))
            self.decoder.close()
            self.encoder.close()
            with self._lock:
                for response in self.responses.values():
                    response.pcm.clear()
                    response.dropped = True
                for marker, _timestamp in self._probe_tx_completed.values():
                    marker.set()
            self._resources_stopped = True
            return all(
                worker is None or not worker.is_alive()
                for worker in (self._boundary_thread, self._tx_thread)
            )

    def stop(self) -> None:
        router = self.radio_router
        if router is not None:
            result = router.shutdown(2.0)
            self.radio_router = None
            if not result.clean:
                self._stop_transport_resources(0.5)
            return
        self._stop_transport_resources(2.0)


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
                radio_stt_provider=request.radio_stt_provider,
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
        main_voice_session_id: str | None = None
        hybrid_attached = False
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
                provider_input_rate_hz=(
                    SRS_DECODE_RATE_HZ
                    if request.radio_stt_provider is RadioSttProvider.SPEECHKIT_V3
                    else YANDEX_INPUT_RATE
                ),
                authoritative_tx_state=(
                    request.radio_stt_provider is RadioSttProvider.SPEECHKIT_V3
                ),
            )
            endpoint.connect_radio()

            def streaming() -> None:
                tx_state_suffix = ""
                if (
                    request.radio_stt_provider is RadioSttProvider.SPEECHKIT_V3
                    and endpoint is not None
                    and endpoint._tx_state_listener is not None
                ):
                    tx_state_suffix = (
                        " | SRS TX STATE: "
                        f"{endpoint._tx_state_listener.status.value.upper()}"
                    )
                self._set(
                    state=YandexSrsState.STREAMING,
                    phase="listening",
                    message=(
                        "SpeechKit v3 SRS voice is running"
                        if request.radio_stt_provider
                        is RadioSttProvider.SPEECHKIT_V3
                        else "Yandex SRS voice is running"
                    )
                    + tx_state_suffix,
                )

            def session_ready(voice_session_id: str) -> None:
                nonlocal main_voice_session_id, hybrid_attached
                from orion.live_golden_conversation import (
                    LiveGoldenRuntimeContext,
                    live_golden_conversation,
                )
                from orion.yandex_hybrid_probe import (
                    HybridRuntimeContext,
                    yandex_hybrid_probe,
                )
                from orion.realtime_test_evidence import realtime_test_evidence

                if endpoint is None:
                    raise RuntimeError(
                        "SRS endpoint is unavailable during provider handshake"
                    )
                main_voice_session_id = voice_session_id
                if request.radio_stt_provider is RadioSttProvider.YANDEX_REALTIME:
                    yandex_hybrid_probe.attach(
                        HybridRuntimeContext(
                            api_key=api_key,
                            folder_id=request.folder_id,
                            endpoint=endpoint,
                            main_session_id=voice_session_id,
                            context_version=(
                                realtime_test_evidence.current_context_version
                            ),
                        )
                    )
                    hybrid_attached = True
                live_golden_conversation.attach(
                    LiveGoldenRuntimeContext(
                        api_key=api_key,
                        folder_id=request.folder_id,
                        endpoint=endpoint,
                        main_session_id=voice_session_id,
                    )
                )

            from orion.live_golden_conversation import live_golden_conversation

            if request.radio_stt_provider is RadioSttProvider.SPEECHKIT_V3:
                from orion.yandex_speechkit_stt import SpeechKitV3RadioSttAdapter

                asyncio.run(
                    SpeechKitV3RadioSttAdapter(
                        api_key,
                        endpoint,
                        stop_event,
                        yandex_diagnostics,
                        on_streaming=streaming,
                        on_session_ready=session_ready,
                        on_finalized_utterance=(
                            live_golden_conversation.accept_native_finalized_utterance
                        ),
                    ).run()
                )
            else:
                asyncio.run(
                    YandexRealtimeSession(
                        api_key,
                        request.folder_id,
                        endpoint,
                        stop_event,
                        yandex_diagnostics,
                        on_streaming=streaming,
                        on_session_ready=session_ready,
                        on_user_transcript_segment=(
                            live_golden_conversation.accept_transcript_segment
                        ),
                        on_input_transmission_started=(
                            live_golden_conversation.input_transmission_started
                        ),
                        on_input_transmission_completed=(
                            live_golden_conversation.input_transmission_completed
                        ),
                        on_provider_input_activity=(
                            live_golden_conversation.provider_input_activity
                        ),
                        suppress_provider_responses=(
                            live_golden_conversation.suppress_provider_responses
                        ),
                    ).run()
                )
        except Exception as exc:
            safe = sanitize_yandex_error(
                sanitize_srs_error(exc, api_key, eam_password),
                api_key,
            )
            srs_diagnostics.record(
                "session_error", error_type=type(exc).__name__, error=safe
            )
            self._set(
                state=YandexSrsState.ERROR,
                phase="idle",
                message=f"{type(exc).__name__}: {safe}",
                last_error=safe,
            )
        finally:
            stop_event.set()
            if main_voice_session_id is not None:
                from orion.live_golden_conversation import live_golden_conversation
                from orion.yandex_hybrid_probe import yandex_hybrid_probe

                live_golden_conversation.detach(main_voice_session_id)
                if hybrid_attached:
                    yandex_hybrid_probe.detach(main_voice_session_id)
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
