from __future__ import annotations

import asyncio
import io
import queue
import threading
import time
import wave
import zipfile

import pytest

from orion.live_golden_conversation import LiveGoldenRuntimeContext
from orion.srs_diagnostics import SrsTransportDiagnostics
from orion.srs_protocol import (
    Frequency,
    VoicePacket,
    decode_voice_packet,
    encode_voice_packet,
)
from orion.srs_radio_transport import SrsRadioConfig, SrsState
from orion.srs_tx_state import (
    SRS_TX_STATE_MAX_LIVENESS_SECONDS,
    SrsTxStateLiveness,
    SrsTxStateListenerStatus,
    SrsTxStateSnapshot,
)
from orion.realtime_audio_transport import (
    FinalizedUserUtterance,
    RealtimeInputTransmissionCompleted,
    RealtimeInputTransmissionStarted,
)
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.radio_streaming import BoundedPcmStream
from orion.yandex_speechkit_stt import (
    SpeechKitProviderEvent,
    SpeechKitV3RadioSttAdapter,
)
from orion.yandex_speechkit_streaming_tts import SpeechKitTtsOutputMode
from orion.yandex_srs_live_core import (
    MAX_RESPONSE_STATES,
    RESPONSE_MAX_BYTES,
    SRS_DECODE_RATE_HZ,
    TRAILING_SILENCE_BLOCKS,
    YANDEX_INPUT_RATE,
    YANDEX_BLOCK_BYTES,
    RadioSttProvider,
    SrsYandexPcmEndpoint,
    YandexSrsLiveService,
    YandexSrsStartRequest,
)

HUMAN = "HHHHHHHHHHHHHHHHHHHHHH"
ORION = "OOOOOOOOOOOOOOOOOOOOOO"


class Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


class FakeCodec:
    def __init__(self, output: bytes) -> None:
        self.output = output
        self.closed = False

    def decode(self, _packet: bytes) -> bytes:
        return self.output

    def encode(self, _pcm: bytes) -> bytes:
        return b"fake-opus"

    def close(self) -> None:
        self.closed = True


class FailOnceDecoder:
    def __init__(self) -> None:
        self.calls = 0

    def decode(self, _packet: bytes) -> bytes:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("deterministic decode failure")
        return bytes(1280)

    def close(self) -> None:
        return None


class FakeResampler:
    def __init__(self, output: bytes) -> None:
        self.output = output
        self.resets = 0

    def process(self, _pcm: bytes, *, end_of_input: bool = False) -> bytes:
        return self.output

    def reset(self) -> None:
        self.resets += 1


class FakeRadio:
    def __init__(self, callback) -> None:  # noqa: ANN001
        self.client_guid = ORION
        self.voice_callback = callback
        self.state = SrsState.DISCONNECTED
        self.server_version = "2.4.0.0"
        self.coalition = 2
        self.radio_registered = False
        self.udp_registered = False
        self.udp_packets_received = 0
        self.udp_packets_sent = 0
        self.sent: list[bytes] = []

    def connect(self) -> None:
        self.state = SrsState.READY
        self.radio_registered = True
        self.udp_registered = True

    def send_voice(self, datagram: bytes) -> None:
        self.sent.append(datagram)
        self.udp_packets_sent += 1

    def close(self) -> None:
        self.state = SrsState.STOPPED


class FakeTxStateListener:
    def __init__(
        self,
        _session_stop,
        on_snapshot,
        on_status,
        _diagnostic,
        *,
        clock,
        initial_sending: bool = False,
    ) -> None:  # noqa: ANN001
        self._on_snapshot = on_snapshot
        self._on_status = on_status
        self._clock = clock
        self._initial_sending = initial_sending
        self.status = SrsTxStateListenerStatus.STOPPED
        self.latest: SrsTxStateSnapshot | None = None
        self._listener_epoch = 1
        self._cadence_intervals: list[float] = []
        self._last_received_at: float | None = None

    @property
    def liveness(self) -> SrsTxStateLiveness:
        observed = max(self._cadence_intervals) if self._cadence_intervals else None
        budget = (
            SRS_TX_STATE_MAX_LIVENESS_SECONDS
            if observed is None
            else min(SRS_TX_STATE_MAX_LIVENESS_SECONDS, max(1.0, 3.0 * observed))
        )
        return SrsTxStateLiveness(
            listener_epoch=self._listener_epoch,
            cadence_sample_count=len(self._cadence_intervals),
            observed_cadence_seconds=observed,
            budget_seconds=budget,
        )

    @property
    def liveness_budget_seconds(self) -> float:
        return self.liveness.budget_seconds

    @property
    def maximum_liveness_seconds(self) -> float:
        return SRS_TX_STATE_MAX_LIVENESS_SECONDS

    def start(self) -> None:
        self.status = SrsTxStateListenerStatus.READY
        self._on_status(self.status, 0.0)
        self.emit(self._initial_sending)

    def stop(self) -> None:
        self.status = SrsTxStateListenerStatus.STOPPED

    def emit(self, is_sending: bool, sending_on: int = 1) -> None:
        previous = self.latest
        received_at = self._clock()
        if self._last_received_at is not None:
            interval = received_at - self._last_received_at
            if interval > 0:
                self._cadence_intervals.append(interval)
                self._cadence_intervals = self._cadence_intervals[-8:]
        self._last_received_at = received_at
        snapshot = SrsTxStateSnapshot(
            is_sending=is_sending,
            sending_on=sending_on,
            is_encrypted=0,
            received_at=received_at,
            received_timestamp=f"test-{self._clock():.3f}",
        )
        self.latest = snapshot
        self.status = SrsTxStateListenerStatus.READY
        self._on_status(self.status, 0.0)
        self._on_snapshot(snapshot, previous)

    def stale(self, age_ms: float = 1_001.0) -> None:
        self.status = SrsTxStateListenerStatus.STALE
        self._listener_epoch += 1
        self._cadence_intervals.clear()
        self._last_received_at = None
        self.latest = None
        self._on_status(self.status, age_ms)


def make_endpoint(
    tmp_path,
    clock: Clock,
    *,
    provider_input_rate_hz: int = 44_100,
    decoded_pcm: bytes = bytes(1280),
    authoritative_tx_state: bool = False,
    tx_state_initial_sending: bool = False,
):  # noqa: ANN001, ANN201
    radio_holder: list[FakeRadio] = []

    def radio_factory(_config, callback, _events):  # noqa: ANN001, ANN202
        radio = FakeRadio(callback)
        radio_holder.append(radio)
        return radio

    status: dict[str, object] = {}

    def update(**changes: object) -> None:
        status.update(changes)

    def tx_state_listener_factory(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return FakeTxStateListener(
            *args,
            **kwargs,
            initial_sending=tx_state_initial_sending,
        )

    endpoint = SrsYandexPcmEndpoint(
        SrsRadioConfig(eam_password="memory-only"),
        threading.Event(),
        SrsTransportDiagnostics("test", secrets=("memory-only",), runtime_dir=tmp_path),
        update,
        radio_factory=radio_factory,
        decoder_factory=lambda: FakeCodec(decoded_pcm),  # type: ignore[arg-type]
        encoder_factory=lambda: FakeCodec(b""),  # type: ignore[arg-type]
        rx_resampler_factory=lambda: FakeResampler(b"r" * YANDEX_BLOCK_BYTES),  # type: ignore[arg-type]
        tx_resampler_factory=lambda: FakeResampler(bytes(1280 * 2 + 200)),  # type: ignore[arg-type]
        clock=clock,
        provider_input_rate_hz=provider_input_rate_hz,
        authoritative_tx_state=authoritative_tx_state,
        tx_state_listener_factory=tx_state_listener_factory,
    )
    return endpoint, radio_holder[0], status


def human_packet(packet_id: int = 1) -> bytes:
    return encode_voice_packet(
        VoicePacket(
            audio=b"human-opus",
            frequencies=(Frequency(251_000_000.0, 0),),
            unit_id=1,
            packet_id=packet_id,
            retransmission_count=0,
            original_client_guid=HUMAN,
            current_sender_guid=HUMAN,
        )
    )


def test_srs_rx_decode_resample_historical_tail_boundary_and_completed_tx(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, radio, status = make_endpoint(tmp_path, clock)
    endpoint.connect_radio()
    endpoint.start()
    endpoint._on_radio_datagram(human_packet())
    started = endpoint.read_input(0.1)
    assert started == RealtimeInputTransmissionStarted("srs-ptt-000001")
    assert endpoint.read_input(0.1) == b"r" * YANDEX_BLOCK_BYTES
    assert endpoint.decoded_samples == 640
    assert endpoint.resampled_rx_samples == YANDEX_BLOCK_BYTES // 2

    clock.now = 10.7
    deadline = time.monotonic() + 1.0
    queued: list[object] = []
    while len(queued) < TRAILING_SILENCE_BLOCKS + 1 and time.monotonic() < deadline:
        try:
            queued.append(endpoint.input_queue.get(timeout=0.05))
        except queue.Empty:
            pass
    assert queued[:-1] == [bytes(YANDEX_BLOCK_BYTES)] * TRAILING_SILENCE_BLOCKS
    assert isinstance(queued[-1], RealtimeInputTransmissionCompleted)
    assert queued[-1].transmission_id == "srs-ptt-000001"
    assert endpoint.input_queue.empty()

    endpoint.response_started("r1")
    endpoint.response_audio("r1", b"y" * YANDEX_BLOCK_BYTES)
    endpoint.response_audio_done("r1")
    assert radio.sent == []
    endpoint.response_done("r1", "completed")
    deadline = time.monotonic() + 2.0
    while len(radio.sent) < 3 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(radio.sent) == 3
    assert status["tx_frames"] == 3
    events = endpoint.diagnostics.snapshot()
    tx_started = [event for event in events if event["event"] == "srs_tx_started"]
    assert len(tx_started) == 1
    assert tx_started[0]["response_id"] == "r1"
    assert tx_started[0]["packet_id"] == 1
    endpoint.stop()


def test_streaming_srs_tx_opens_once_and_completes_only_after_source_drain(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, radio, _status = make_endpoint(tmp_path, clock)
    endpoint.connect_radio()
    endpoint.start()
    source = BoundedPcmStream(
        "streaming-srs-1",
        sample_rate_hz=44_100,
        prebuffer_ms=100,
        max_buffer_ms=200,
        max_total_bytes=44_100,
        capture=True,
    )
    expected = b"\x01\x00" * 8_820
    source.feed(expected)
    source.finish()
    completion = endpoint.transmit_srs_pcm_stream(
        "streaming-srs-1",
        source,
        2.0,
    )
    assert completion.frame_count > 0
    assert source.snapshot().buffered_bytes == 0
    assert source.snapshot().captured_pcm == expected
    assert radio.sent
    starts = [
        event
        for event in endpoint.diagnostics.snapshot()
        if event["event"] == "srs_tx_started"
        and event.get("response_id") == "streaming-srs-1"
    ]
    assert len(starts) == 1
    endpoint.stop()


def test_streaming_srs_tx_inserts_at_most_120ms_silence_then_aborts_stall(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, radio, _status = make_endpoint(tmp_path, clock)
    endpoint.connect_radio()
    endpoint.start()
    source = BoundedPcmStream(
        "streaming-stall-1",
        sample_rate_hz=44_100,
        prebuffer_ms=100,
        max_buffer_ms=200,
        max_total_bytes=44_100,
    )
    source.feed(b"\x01\x00" * 4_410)
    with pytest.raises(RuntimeError, match="bounded underrun policy"):
        endpoint.transmit_srs_pcm_stream("streaming-stall-1", source, 2.0)
    assert source.snapshot().state.value == "failed"
    # The fake resampler yields two source-backed frames. Exactly three more
    # frames are allowed by the 120 ms continuity budget; the fourth gap aborts.
    assert len(radio.sent) == 5
    endpoint.stop()


def test_speechkit_input_uses_original_16khz_pcm_without_realtime_resample_or_tail(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
    )
    endpoint.connect_radio()
    endpoint.start()
    endpoint._on_radio_datagram(human_packet())

    assert endpoint.pcm_format == endpoint.pcm_format.__class__(sample_rate=16_000)
    assert endpoint.read_input(0.1) == RealtimeInputTransmissionStarted(
        "srs-ptt-000001"
    )
    assert endpoint.read_input(0.1) == bytes(640)
    assert endpoint.read_input(0.1) == bytes(640)
    assert endpoint.resampled_rx_samples == 0

    clock.now = 10.7
    completed = endpoint.read_input(1.0)
    assert isinstance(completed, RealtimeInputTransmissionCompleted)
    assert completed.transmission_id == "srs-ptt-000001"
    assert endpoint.input_queue.empty()
    events = endpoint.diagnostics.snapshot()
    boundary = next(
        event for event in events if event["event"] == "rx_transmission_completed"
    )
    assert boundary["trailing_silence_ms"] == 0
    endpoint.stop()


def test_speechkit_srs_packet_timeline_and_pcm_accounting_are_exact(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        decoded_pcm=bytes(1_000),
    )
    endpoint.connect_radio()
    endpoint.start()
    endpoint._on_radio_datagram(human_packet(10))
    clock.now = 10.02
    endpoint._on_radio_datagram(human_packet(12))

    assert endpoint.read_input(0.1) == RealtimeInputTransmissionStarted(
        "srs-ptt-000001"
    )
    assert endpoint.read_input(0.1) == bytes(640)
    assert endpoint.read_input(0.1) == bytes(640)
    assert endpoint.read_input(0.1) == bytes(640)
    clock.now = 10.7
    assert endpoint.read_input(1.0) == bytes(640)
    completed = endpoint.read_input(0.1)
    assert isinstance(completed, RealtimeInputTransmissionCompleted)
    assert completed.transmission_id == "srs-ptt-000001"
    assert completed.accepted_packet_count == 2
    assert completed.first_packet_id == 10
    assert completed.last_packet_id == 12
    assert completed.sequence_gap_count == 1
    assert completed.decode_error_count == 0
    assert completed.decoded_pcm_bytes == 2_000
    assert completed.padding_bytes == 560
    assert completed.framed_pcm_bytes == 2_560
    assert (
        completed.decoded_pcm_bytes + completed.padding_bytes
        == completed.framed_pcm_bytes
    )
    assert completed.first_accepted_packet_timestamp
    assert completed.last_accepted_packet_timestamp
    assert completed.packet_quiescence_completed_timestamp
    assert completed.boundary_gap_ms == 400

    boundary = next(
        event
        for event in endpoint.diagnostics.snapshot()
        if event["event"] == "rx_transmission_completed"
    )
    assert boundary["accepted_packet_count"] == 2
    assert boundary["first_packet_id"] == 10
    assert boundary["last_packet_id"] == 12
    assert boundary["sequence_gap_count"] == 1
    assert boundary["decoded_pcm_bytes"] == 2_000
    assert boundary["padding_bytes"] == 560
    assert boundary["framed_pcm_bytes"] == 2_560
    endpoint.stop()


def test_speechkit_srs_timeline_counts_accepted_packet_decode_errors(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
    )
    endpoint.decoder = FailOnceDecoder()  # type: ignore[assignment]
    endpoint.connect_radio()
    endpoint.start()
    endpoint._on_radio_datagram(human_packet(1))
    clock.now = 10.02
    endpoint._on_radio_datagram(human_packet(2))

    assert endpoint.read_input(0.1) == RealtimeInputTransmissionStarted(
        "srs-ptt-000001"
    )
    assert endpoint.read_input(0.1) == bytes(640)
    assert endpoint.read_input(0.1) == bytes(640)
    clock.now = 10.7
    completed = endpoint.read_input(1.0)
    assert isinstance(completed, RealtimeInputTransmissionCompleted)
    assert completed.accepted_packet_count == 2
    assert completed.decode_error_count == 1
    assert completed.decoded_pcm_bytes == 1_280
    assert completed.framed_pcm_bytes == 1_280
    endpoint.stop()


def test_authoritative_tx_state_false_true_false_queues_one_completion(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)

    listener.emit(True, 1)
    endpoint._on_radio_datagram(human_packet(1))
    listener.emit(False, 1)
    queued = [endpoint.read_input(0.1) for _ in range(4)]

    assert queued[0] == RealtimeInputTransmissionStarted("srs-ptt-000001")
    assert queued[1:3] == [bytes(640), bytes(640)]
    completed = queued[3]
    assert isinstance(completed, RealtimeInputTransmissionCompleted)
    assert completed.boundary == "srs_tx_state_end"
    assert completed.srs_tx_state_authoritative is True
    assert completed.srs_tx_sending_on == 1
    assert endpoint.input_queue.empty()
    assert endpoint.tracker.counters.transmissions_completed == 1
    endpoint.stop()


def test_authoritative_packet_candidate_waits_for_matching_7082_before_start(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        decoded_pcm=b"\x01\x02" * 640,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)

    clock.now += 0.2
    listener.emit(False, 1)
    endpoint._on_radio_datagram(human_packet(1))
    endpoint._on_radio_datagram(human_packet(2))
    assert endpoint.input_queue.empty()
    assert bytes(endpoint.rx_accumulator) == (b"\x01\x02" * 1_280)

    clock.now += 0.2
    listener.emit(True, 1)
    queued = [endpoint.read_input(0.1) for _ in range(5)]
    assert queued[0] == RealtimeInputTransmissionStarted("srs-ptt-000001")
    assert b"".join(queued[1:]) == (b"\x01\x02" * 1_280)
    assert endpoint.rx_accumulator == bytearray()
    promoted = next(
        event
        for event in endpoint.diagnostics.snapshot()
        if event["event"] == "srs_packet_candidate_promoted"
    )
    assert promoted["candidate_pcm_bytes"] == 2_560
    assert promoted["correlation_wait_ms"] == 200.0
    listener.emit(False, 1)
    assert isinstance(
        endpoint.read_input(0.1),
        RealtimeInputTransmissionCompleted,
    )
    endpoint.stop()


def test_false_only_packet_candidate_is_discarded_without_provider_turn(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)

    clock.now += 0.2
    listener.emit(False, 1)
    endpoint._on_radio_datagram(human_packet(1))
    assert endpoint.input_queue.empty()
    clock.now += 1.1
    deadline = time.monotonic() + 0.5
    while endpoint._active_rx_transmission_id is not None and time.monotonic() < deadline:
        time.sleep(0.01)

    assert endpoint._active_rx_transmission_id is None
    assert endpoint.input_queue.empty()
    assert endpoint.failure() is None
    assert endpoint.rx_accumulator == bytearray()
    assert endpoint.tracker.counters.transmissions_completed == 0
    discarded = next(
        event
        for event in endpoint.diagnostics.snapshot()
        if event["event"] == "srs_packet_candidate_discarded"
    )
    assert discarded["reason"] == "tx_state_not_confirmed"
    assert discarded["candidate_pcm_bytes"] == 1_280
    assert discarded["eou_triggered_by_7082"] is False
    endpoint.stop()


def test_unconfirmed_packet_candidate_pcm_is_bounded_and_discarded(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)
    clock.now += 0.2
    listener.emit(False, 1)

    for packet_id in range(1, 127):
        endpoint._on_radio_datagram(human_packet(packet_id))

    assert endpoint.input_queue.empty()
    assert endpoint.failure() is None
    assert endpoint.rx_accumulator == bytearray()
    assert endpoint._active_rx_transmission_id is None
    discarded = [
        event
        for event in endpoint.diagnostics.snapshot()
        if event["event"] == "srs_packet_candidate_discarded"
    ]
    assert len(discarded) == 1
    assert discarded[0]["reason"] == "pcm_buffer_limit"
    assert discarded[0]["candidate_pcm_bytes"] == 160_000
    assert discarded[0]["candidate_pcm_limit_bytes"] == 160_000
    assert discarded[0]["candidate_buffered_duration_ms"] == 5_000.0
    endpoint.stop()


def test_authoritative_tx_state_ignores_packet_gap_while_srs_tx_remains_true(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)
    listener.emit(True, 1)
    endpoint._on_radio_datagram(human_packet(1))
    clock.now += 0.7
    time.sleep(0.06)

    assert not any(
        isinstance(item, RealtimeInputTransmissionCompleted)
        for item in tuple(endpoint.input_queue.queue)
    )
    assert endpoint._channel_clear_for_tx(clock()) is False
    endpoint._on_radio_datagram(human_packet(2))
    listener.emit(True, 1)
    listener.emit(False, 1)
    assert endpoint._channel_clear_for_tx(clock()) is False
    clock.now += 0.25
    assert endpoint._channel_clear_for_tx(clock()) is True
    queued = []
    while not endpoint.input_queue.empty():
        queued.append(endpoint.input_queue.get_nowait())
    assert sum(isinstance(item, RealtimeInputTransmissionCompleted) for item in queued) == 1
    assert endpoint.tracker.counters.transmissions_started == 1
    endpoint.stop()


def test_authoritative_tx_end_flushes_final_pcm_before_completion_marker(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        decoded_pcm=bytes(1_000),
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)
    listener.emit(True, 1)
    endpoint._on_radio_datagram(human_packet(1))
    listener.emit(False, 1)

    queued = [endpoint.read_input(0.1) for _ in range(4)]
    assert queued[0] == RealtimeInputTransmissionStarted("srs-ptt-000001")
    assert queued[1:3] == [bytes(640), bytes(640)]
    completed = queued[3]
    assert isinstance(completed, RealtimeInputTransmissionCompleted)
    assert completed.decoded_pcm_bytes == 1_000
    assert completed.padding_bytes == 280
    assert completed.framed_pcm_bytes == 1_280
    endpoint.stop()


def test_authoritative_false_without_confirmed_true_never_queues_ghost_eou(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)
    listener.emit(False, 1)
    assert endpoint.input_queue.empty()
    assert endpoint.tracker.counters.transmissions_completed == 0
    endpoint.stop()


def test_listener_starting_mid_tx_correlates_voice_and_closes_on_later_false(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
        tx_state_initial_sending=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)
    endpoint._on_radio_datagram(human_packet(1))
    listener.emit(False, 1)

    queued = []
    while not endpoint.input_queue.empty():
        queued.append(endpoint.input_queue.get_nowait())
    completed = [
        item for item in queued if isinstance(item, RealtimeInputTransmissionCompleted)
    ]
    assert len(completed) == 1
    started = next(
        event
        for event in endpoint.diagnostics.snapshot()
        if event["event"] == "srs_tx_started"
    )
    assert started["transition_authoritative"] is False
    endpoint.stop()


def test_three_authoritative_tx_cycles_remain_independent(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)

    for packet_id in range(1, 4):
        listener.emit(True, 1)
        endpoint._on_radio_datagram(human_packet(packet_id))
        listener.emit(False, 1)
    queued = []
    while not endpoint.input_queue.empty():
        queued.append(endpoint.input_queue.get_nowait())
    starts = [item for item in queued if isinstance(item, RealtimeInputTransmissionStarted)]
    ends = [item for item in queued if isinstance(item, RealtimeInputTransmissionCompleted)]
    assert [item.transmission_id for item in starts] == [
        "srs-ptt-000001",
        "srs-ptt-000002",
        "srs-ptt-000003",
    ]
    assert [item.transmission_id for item in ends] == [item.transmission_id for item in starts]
    endpoint.stop()


def test_three_7082_tx_cycles_emit_three_eous_on_one_persistent_rpc(
    tmp_path,
) -> None:  # noqa: ANN001
    class Port:
        def __init__(self) -> None:
            self.responses: asyncio.Queue[SpeechKitProviderEvent | None] = (
                asyncio.Queue()
            )
            self.open_count = 0
            self.eou_count = 0
            self.audio: list[bytes] = []

        async def open(self, _api_key: str) -> None:
            self.open_count += 1

        async def send_audio(self, pcm16le: bytes) -> None:
            self.audio.append(pcm16le)

        async def send_eou(self) -> None:
            index = self.eou_count
            self.eou_count += 1
            cursor = (index + 1) * 1_000
            common = {
                "session_uuid": "one-persistent-session",
                "final_index": index,
                "received_data_ms": cursor,
                "final_time_ms": cursor,
                "eou_time_ms": cursor,
            }
            await self.responses.put(
                SpeechKitProviderEvent(
                    kind="final",
                    transcript=f"turn {index + 1}",
                    **common,
                )
            )
            await self.responses.put(SpeechKitProviderEvent(kind="eou_update", **common))

        async def receive(self) -> SpeechKitProviderEvent | None:
            return await self.responses.get()

        async def done_writing(self) -> None:
            await self.responses.put(None)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        clock = Clock()
        endpoint, _radio, _status = make_endpoint(
            tmp_path,
            clock,
            provider_input_rate_hz=16_000,
            authoritative_tx_state=True,
        )
        endpoint.connect_radio()
        listener = endpoint._tx_state_listener
        assert isinstance(listener, FakeTxStateListener)
        port = Port()
        utterances: list[FinalizedUserUtterance] = []
        adapter = SpeechKitV3RadioSttAdapter(
            "memory-only",
            endpoint,
            endpoint.stop_event,
            endpoint.diagnostics,
            port_factory=lambda: port,
            on_finalized_utterance=utterances.append,
        )
        task = asyncio.create_task(adapter.run())
        while not endpoint._started:
            await asyncio.sleep(0.001)
        for packet_id in range(1, 4):
            listener.emit(True, 1)
            endpoint._on_radio_datagram(human_packet(packet_id))
            listener.emit(False, 1)
            deadline = time.monotonic() + 1.0
            while len(utterances) < packet_id and time.monotonic() < deadline:
                await asyncio.sleep(0.001)
            assert len(utterances) == packet_id
        endpoint.stop_event.set()
        await task

        assert [item.transcript for item in utterances] == ["turn 1", "turn 2", "turn 3"]
        assert port.eou_count == 3
        assert port.open_count == 1
        assert len(port.audio) == 6

    asyncio.run(scenario())


def test_empty_turn_then_false_only_candidate_then_real_turn_is_clean(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    class Port:
        def __init__(self) -> None:
            self.responses: asyncio.Queue[SpeechKitProviderEvent | None] = (
                asyncio.Queue()
            )
            self.eou_count = 0
            self.audio: list[bytes] = []

        async def open(self, _api_key: str) -> None:
            return None

        async def send_audio(self, pcm16le: bytes) -> None:
            self.audio.append(pcm16le)

        async def send_eou(self) -> None:
            index = self.eou_count
            self.eou_count += 1
            cursor = (index + 1) * 1_000
            common = {
                "session_uuid": "empty-then-real-session",
                "final_index": index,
                "received_data_ms": cursor,
                "final_time_ms": cursor,
                "eou_time_ms": cursor,
            }
            await self.responses.put(
                SpeechKitProviderEvent(
                    kind="final",
                    transcript="" if index == 0 else "добрый день",
                    **common,
                )
            )
            await self.responses.put(SpeechKitProviderEvent(kind="eou_update", **common))

        async def receive(self) -> SpeechKitProviderEvent | None:
            return await self.responses.get()

        async def done_writing(self) -> None:
            await self.responses.put(None)

        async def close(self) -> None:
            return None

    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(
        provider="yandex",
        transport="srs",
        radio_stt_provider="speechkit_v3_external_eou",
        capture_speechkit_stt_input_audio=True,
    )
    monkeypatch.setattr(
        "orion.yandex_speechkit_stt.realtime_test_evidence",
        recorder,
    )

    async def scenario() -> Port:
        clock = Clock()
        expected_pcm = b"\x01\x02" * 640
        endpoint, _radio, _status = make_endpoint(
            tmp_path,
            clock,
            provider_input_rate_hz=16_000,
            decoded_pcm=expected_pcm,
            authoritative_tx_state=True,
        )
        endpoint.connect_radio()
        listener = endpoint._tx_state_listener
        assert isinstance(listener, FakeTxStateListener)
        port = Port()
        utterances: list[FinalizedUserUtterance] = []
        adapter = SpeechKitV3RadioSttAdapter(
            "memory-only",
            endpoint,
            endpoint.stop_event,
            endpoint.diagnostics,
            port_factory=lambda: port,
            on_finalized_utterance=utterances.append,
        )
        task = asyncio.create_task(adapter.run())
        while not endpoint._started:
            await asyncio.sleep(0.001)

        endpoint._on_radio_datagram(human_packet(1))
        listener.emit(True, 1)
        listener.emit(False, 1)
        deadline = time.monotonic() + 1.0
        while not any(
            event["event"] == "speechkit_stt_barrier_completed"
            for event in endpoint.diagnostics.snapshot()
        ):
            assert time.monotonic() < deadline
            await asyncio.sleep(0.001)
        assert adapter.state.value == "ready"
        assert utterances == []

        clock.now += 18.0
        endpoint._on_radio_datagram(human_packet(2))
        assert endpoint.input_queue.empty()
        clock.now += 5.1
        deadline = time.monotonic() + 1.0
        while endpoint._active_rx_transmission_id is not None:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.001)
        assert port.eou_count == 1
        assert adapter.state.value == "ready"
        assert endpoint.failure() is None

        endpoint._on_radio_datagram(human_packet(3))
        listener.emit(True, 1)
        listener.emit(False, 1)
        while not utterances:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.001)
        endpoint.stop_event.set()
        await task

        assert [(item.transmission_id, item.transcript) for item in utterances] == [
            ("srs-ptt-000003", "добрый день")
        ]
        assert utterances[0].provider_final_index == 1
        assert port.eou_count == 2
        assert b"".join(port.audio) == expected_pcm * 2
        discarded = [
            event
            for event in endpoint.diagnostics.snapshot()
            if event["event"] == "srs_packet_candidate_discarded"
        ]
        assert len(discarded) == 1
        assert discarded[0]["physical_transmission_id"] == "srs-ptt-000002"
        return port

    port = asyncio.run(scenario())
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        wav_names = sorted(
            name
            for name in archive.namelist()
            if name.startswith("speechkit-stt-input/") and name.endswith(".wav")
        )
        assert wav_names == [
            "speechkit-stt-input/srs-ptt-000001.wav",
            "speechkit-stt-input/srs-ptt-000003.wav",
        ]
        for name in wav_names:
            with wave.open(io.BytesIO(archive.read(name)), "rb") as captured:
                assert (
                    captured.getframerate(),
                    captured.getnchannels(),
                    captured.getsampwidth(),
                ) == (16_000, 1, 2)
                assert captured.readframes(captured.getnframes()) == b"".join(
                    port.audio[:2]
                )


def test_authoritative_tx_state_stale_during_active_turn_fails_closed(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)
    listener.emit(True, 1)
    endpoint._on_radio_datagram(human_packet(1))
    listener.stale()

    assert isinstance(endpoint.failure(), RuntimeError)
    assert not any(
        isinstance(item, RealtimeInputTransmissionCompleted)
        for item in tuple(endpoint.input_queue.queue)
    )
    endpoint.stop()


def test_authoritative_tx_state_can_recover_while_idle(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)
    listener.stale()
    assert endpoint.failure() is None
    listener.emit(False, 1)
    assert status["srs_tx_state_status"] == "ready"
    assert endpoint.failure() is None
    endpoint.stop()


def test_2026_09_01_slow_7082_candidate_survives_old_one_second_failure(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)

    clock.now += 1.6
    listener.emit(False, 1)
    assert listener.liveness.budget_seconds == pytest.approx(4.8)
    clock.now += 0.5
    endpoint._on_radio_datagram(human_packet(1))
    endpoint._on_radio_datagram(human_packet(2))
    assert endpoint.input_queue.empty()

    clock.now += 1.1
    time.sleep(0.05)
    assert endpoint._active_rx_transmission_id == "srs-ptt-000001"
    assert endpoint.failure() is None
    listener.emit(True, 1)

    assert endpoint.read_input(0.1) == RealtimeInputTransmissionStarted(
        "srs-ptt-000001"
    )
    assert b"".join(endpoint.read_input(0.1) for _ in range(4)) == bytes(2_560)
    for _ in range(3):
        clock.now += 1.6
        listener.emit(True, 1)
    clock.now += 1.6
    listener.emit(False, 1)
    completed = endpoint.read_input(0.1)
    assert isinstance(completed, RealtimeInputTransmissionCompleted)
    assert completed.transmission_id == "srs-ptt-000001"
    assert endpoint.failure() is None

    events = endpoint.diagnostics.snapshot()
    candidate = next(
        event for event in events if event["event"] == "srs_packet_candidate_started"
    )
    promoted = next(
        event for event in events if event["event"] == "srs_packet_candidate_promoted"
    )
    assert candidate["confirmation_timeout_ms"] == pytest.approx(4_800.0)
    assert candidate["candidate_pcm_limit_bytes"] == 160_000
    assert promoted["correlation_wait_ms"] == pytest.approx(1_100.0)
    assert sum(event["event"] == "rx_transmission_completed" for event in events) == 1
    endpoint.stop()


def test_reconnect_epoch_bootstrap_forgets_fast_cadence_and_accepts_slow_true(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)

    clock.now += 0.2
    listener.emit(False, 1)
    assert listener.liveness.budget_seconds == 1.0
    listener.stale()
    assert endpoint.failure() is None
    assert listener.liveness.budget_seconds == 5.0

    clock.now += 1.6
    listener.emit(False, 1)
    clock.now += 0.5
    endpoint._on_radio_datagram(human_packet(1))
    clock.now += 1.1
    time.sleep(0.05)
    assert endpoint._active_rx_transmission_id == "srs-ptt-000001"
    listener.emit(True, 1)
    assert endpoint.read_input(0.1) == RealtimeInputTransmissionStarted(
        "srs-ptt-000001"
    )
    clock.now += 1.6
    listener.emit(False, 1)
    assert any(
        isinstance(item, RealtimeInputTransmissionCompleted)
        for item in tuple(endpoint.input_queue.queue)
    )
    assert endpoint.failure() is None
    endpoint.stop()


def test_unconfirmed_candidate_does_not_turn_stale_into_authoritative_failure(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)

    endpoint._on_radio_datagram(human_packet(1))
    listener.stale()
    assert endpoint.failure() is None
    clock.now += 5.001
    time.sleep(0.05)

    assert endpoint._active_rx_transmission_id is None
    assert endpoint.failure() is None
    assert not any(
        isinstance(item, RealtimeInputTransmissionCompleted)
        for item in tuple(endpoint.input_queue.queue)
    )
    discarded = next(
        event
        for event in endpoint.diagnostics.snapshot()
        if event["event"] == "srs_packet_candidate_discarded"
    )
    assert discarded["reason"] == "tx_state_not_confirmed"
    assert discarded["tx_state_confirmed"] is False
    endpoint.stop()


def test_wrong_sending_on_discards_candidate_without_provider_turn(
    tmp_path,
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, _radio, _status = make_endpoint(
        tmp_path,
        clock,
        provider_input_rate_hz=16_000,
        authoritative_tx_state=True,
    )
    endpoint.connect_radio()
    endpoint.start()
    listener = endpoint._tx_state_listener
    assert isinstance(listener, FakeTxStateListener)
    clock.now += 0.2
    listener.emit(False, 1)
    listener.emit(True, 2)
    endpoint._on_radio_datagram(human_packet(1))
    listener.emit(False, 2)
    assert endpoint.input_queue.empty()
    clock.now += 1.1
    deadline = time.monotonic() + 0.5
    while endpoint._active_rx_transmission_id is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert endpoint._active_rx_transmission_id is None
    assert endpoint.failure() is None
    assert endpoint.input_queue.empty()
    discarded = next(
        event
        for event in endpoint.diagnostics.snapshot()
        if event["event"] == "srs_packet_candidate_discarded"
    )
    assert discarded["sending_on"] == 2
    assert discarded["reason"] == "tx_state_not_confirmed"
    endpoint.stop()


def test_service_selector_instantiates_speechkit_adapter_only(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, int]] = []
    live_contexts: list[LiveGoldenRuntimeContext] = []

    class Endpoint:
        def connect_radio(self) -> None:
            calls.append(("connect", 0))

        def stop(self) -> None:
            calls.append(("stop", 0))

    def endpoint_factory(
        *_args,
        provider_input_rate_hz: int,
        authoritative_tx_state: bool,
        **_kwargs,
    ):  # noqa: ANN202
        calls.append(("endpoint_rate", provider_input_rate_hz))
        calls.append(("authoritative_tx_state", int(authoritative_tx_state)))
        return Endpoint()

    class Adapter:
        def __init__(self, *_args, **kwargs) -> None:  # noqa: ANN002, ANN003
            calls.append(("speechkit", 0))
            self._on_session_ready = kwargs["on_session_ready"]

        async def run(self) -> None:
            self._on_session_ready("speechkit-session")

    class ForbiddenRealtime:
        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("Legacy Realtime must not be instantiated")

    monkeypatch.setattr(
        "orion.yandex_speechkit_stt.SpeechKitV3RadioSttAdapter",
        Adapter,
    )
    monkeypatch.setattr(
        "orion.yandex_srs_live_core.YandexRealtimeSession",
        ForbiddenRealtime,
    )
    monkeypatch.setattr(
        "orion.live_golden_conversation.live_golden_conversation.attach",
        live_contexts.append,
    )
    monkeypatch.setattr(
        "orion.live_golden_conversation.live_golden_conversation.detach",
        lambda _session_id: None,
    )
    service = YandexSrsLiveService(endpoint_factory=endpoint_factory)
    service._run(
        YandexSrsStartRequest(
            api_key="memory-only",
            folder_id="folder",
            eam_password="eam-memory-only",
            radio_stt_provider=RadioSttProvider.SPEECHKIT_V3,
            tts_output_mode=SpeechKitTtsOutputMode.STREAMING_V3,
        ),
        "session-speechkit",
        threading.Event(),
    )

    assert ("endpoint_rate", SRS_DECODE_RATE_HZ) in calls
    assert ("authoritative_tx_state", 1) in calls
    assert ("speechkit", 0) in calls
    assert len(live_contexts) == 1
    assert (
        live_contexts[0].tts_output_mode
        is SpeechKitTtsOutputMode.STREAMING_V3
    )


def test_service_selector_instantiates_legacy_realtime_only(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, int]] = []

    class Endpoint:
        def connect_radio(self) -> None:
            calls.append(("connect", 0))

        def stop(self) -> None:
            calls.append(("stop", 0))

    def endpoint_factory(
        *_args,
        provider_input_rate_hz: int,
        authoritative_tx_state: bool,
        **_kwargs,
    ):  # noqa: ANN202
        calls.append(("endpoint_rate", provider_input_rate_hz))
        calls.append(("authoritative_tx_state", int(authoritative_tx_state)))
        return Endpoint()

    class Session:
        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            calls.append(("realtime", 0))

        async def run(self) -> None:
            return None

    class ForbiddenSpeechKit:
        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("SpeechKit must not be instantiated")

    monkeypatch.setattr("orion.yandex_srs_live_core.YandexRealtimeSession", Session)
    monkeypatch.setattr(
        "orion.yandex_speechkit_stt.SpeechKitV3RadioSttAdapter",
        ForbiddenSpeechKit,
    )
    service = YandexSrsLiveService(endpoint_factory=endpoint_factory)
    service._run(
        YandexSrsStartRequest(
            api_key="memory-only",
            folder_id="folder",
            eam_password="eam-memory-only",
            radio_stt_provider=RadioSttProvider.YANDEX_REALTIME,
        ),
        "session-realtime",
        threading.Event(),
    )

    assert ("endpoint_rate", YANDEX_INPUT_RATE) in calls
    assert ("authoritative_tx_state", 0) in calls
    assert ("realtime", 0) in calls


def test_incomplete_cancelled_oversized_and_stop_never_transmit(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    clock = Clock()
    endpoint, radio, _status = make_endpoint(tmp_path, clock)
    endpoint.connect_radio()
    endpoint.start()
    endpoint.response_started("incomplete")
    endpoint.response_audio("incomplete", b"a" * 100)
    endpoint.response_audio_done("incomplete")
    endpoint.response_started("cancelled")
    endpoint.response_audio("cancelled", b"b" * 100)
    endpoint.response_audio_done("cancelled")
    endpoint.response_done("cancelled", "cancelled")
    assert RESPONSE_MAX_BYTES > 1_000_000
    monkeypatch.setattr("orion.yandex_srs_live_core.RESPONSE_MAX_BYTES", 64)
    endpoint.response_started("too-large")
    endpoint.response_audio("too-large", b"c" * 66)
    endpoint.response_audio_done("too-large")
    endpoint.response_done("too-large", "completed")
    time.sleep(0.05)
    assert radio.sent == []
    endpoint.stop()
    assert radio.sent == []


def test_live_golden_provider_output_suppression_drops_realtime_pcm_before_tx(
    tmp_path,
) -> None:  # noqa: ANN001
    endpoint, radio, _status = make_endpoint(tmp_path, Clock())
    endpoint.connect_radio()
    endpoint.start()
    endpoint.set_provider_output_suppressed(True)
    endpoint.response_started("suppressed-yandex-response")
    endpoint.response_audio("suppressed-yandex-response", bytes(400))
    endpoint.response_audio_done("suppressed-yandex-response")
    endpoint.response_done("suppressed-yandex-response", "completed")
    time.sleep(0.05)
    assert radio.sent == []
    assert endpoint.tx_queue.empty()
    endpoint.set_provider_output_suppressed(False)
    endpoint.stop()


def test_provider_input_backpressure_is_bounded_and_reported(tmp_path) -> None:  # noqa: ANN001
    endpoint, _radio, _status = make_endpoint(tmp_path, Clock())
    for _ in range(endpoint.input_queue.maxsize):
        endpoint.input_queue.put_nowait(bytes(YANDEX_BLOCK_BYTES))

    assert endpoint._enqueue_input(bytes(YANDEX_BLOCK_BYTES)) is False
    failure = endpoint.failure()
    assert isinstance(failure, RuntimeError)
    assert "hard bound" in str(failure)
    assert endpoint.stop_event.is_set()
    endpoint.stop()


def test_response_state_table_has_a_hard_bound(tmp_path) -> None:  # noqa: ANN001
    endpoint, _radio, _status = make_endpoint(tmp_path, Clock())
    for index in range(MAX_RESPONSE_STATES + 5):
        endpoint.response_started(f"response-{index}")
        endpoint.response_audio(f"response-{index}", b"\x00\x00")

    assert len(endpoint.responses) == MAX_RESPONSE_STATES
    assert set(endpoint.responses) == {
        f"response-{index}" for index in range(5, MAX_RESPONSE_STATES + 5)
    }
    endpoint.stop()


def test_radio_registration_events_forward_real_launcher_phases(tmp_path) -> None:  # noqa: ANN001
    endpoint, _radio, status = make_endpoint(tmp_path, Clock())

    endpoint._on_radio_event("srs.state", {"value": "REGISTERING_RADIO"})
    assert status["phase"] == "registering_radio"
    endpoint._on_radio_event("srs.state", {"value": "REGISTERING_UDP"})
    assert status["phase"] == "registering_udp"
    endpoint._on_radio_event("srs.state", {"value": "READY"})
    assert status["phase"] == "provider_connecting"
    endpoint.stop()


def test_probe_tx_uses_existing_single_slot_queue_and_waits_for_matching_completion(
    tmp_path,
) -> None:  # noqa: ANN001
    endpoint, radio, _status = make_endpoint(tmp_path, Clock())
    endpoint.connect_radio()
    endpoint.start()
    report = endpoint.transmit_probe_audio("ia11-case-realtime", bytes(400), 2.0)
    assert endpoint.tx_queue.maxsize == 1
    assert radio.sent
    assert report["queue_to_first_tx_ms"] >= 0
    assert report["queue_to_complete_ms"] >= report["queue_to_first_tx_ms"]
    assert not any(
        event["event"] == "response_queue_full"
        for event in endpoint.diagnostics.snapshot()
    )
    endpoint.stop()


def test_router_adapter_and_legacy_response_reuse_identical_srs_wire_mechanics(
    tmp_path,
) -> None:  # noqa: ANN001
    endpoint, radio, _status = make_endpoint(tmp_path, Clock())
    endpoint.connect_radio()
    endpoint.start()

    endpoint.response_started("legacy-response")
    endpoint.response_audio("legacy-response", bytes(400))
    endpoint.response_audio_done("legacy-response")
    endpoint.response_done("legacy-response", "completed")
    deadline = time.monotonic() + 2.0
    while len(radio.sent) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    legacy = tuple(decode_voice_packet(packet) for packet in radio.sent)
    radio.sent.clear()

    report = endpoint.transmit_probe_audio("router-adapter-response", bytes(400), 2.0)
    adapted = tuple(decode_voice_packet(packet) for packet in radio.sent)

    assert len(legacy) == len(adapted) == 3
    assert report["queue_to_complete_ms"] >= report["queue_to_first_tx_ms"]
    for direct, routed in zip(legacy, adapted, strict=True):
        assert direct.audio == routed.audio == b"fake-opus"
        assert (
            direct.frequencies == routed.frequencies == (Frequency(251_000_000.0, 0),)
        )
        assert direct.unit_id == routed.unit_id == endpoint.config.unit_id
        assert direct.retransmission_count == routed.retransmission_count == 0
        assert direct.original_client_guid == routed.original_client_guid == ORION
        assert direct.current_sender_guid == routed.current_sender_guid == ORION
    completed = [
        event
        for event in endpoint.diagnostics.snapshot()
        if event["event"] == "tx_completed"
    ]
    assert [event["response_id"] for event in completed] == [
        "legacy-response",
        "router-adapter-response",
    ]
    endpoint.stop()


def test_probe_tx_timeout_is_bounded_when_worker_is_not_running(tmp_path) -> None:  # noqa: ANN001
    endpoint, _radio, _status = make_endpoint(tmp_path, Clock())
    endpoint.connect_radio()
    started = time.monotonic()
    try:
        endpoint.transmit_srs_pcm("ia11-timeout", bytes(20), 0.02)
    except TimeoutError:
        pass
    else:
        raise AssertionError("Expected matching tx_completed timeout")
    assert time.monotonic() - started < 0.5
    endpoint.stop()
