from __future__ import annotations

import queue
import threading
import time

from orion.srs_diagnostics import SrsTransportDiagnostics
from orion.srs_protocol import (
    Frequency,
    VoicePacket,
    decode_voice_packet,
    encode_voice_packet,
)
from orion.srs_radio_transport import SrsRadioConfig, SrsState
from orion.realtime_audio_transport import (
    RealtimeInputTransmissionCompleted,
    RealtimeInputTransmissionStarted,
)
from orion.yandex_srs_live_core import (
    MAX_RESPONSE_STATES,
    RESPONSE_MAX_BYTES,
    TRAILING_SILENCE_BLOCKS,
    YANDEX_BLOCK_BYTES,
    SrsYandexPcmEndpoint,
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


def make_endpoint(tmp_path, clock: Clock):  # noqa: ANN001, ANN201
    radio_holder: list[FakeRadio] = []

    def radio_factory(_config, callback, _events):  # noqa: ANN001, ANN202
        radio = FakeRadio(callback)
        radio_holder.append(radio)
        return radio

    status: dict[str, object] = {}

    def update(**changes: object) -> None:
        status.update(changes)

    endpoint = SrsYandexPcmEndpoint(
        SrsRadioConfig(eam_password="memory-only"),
        threading.Event(),
        SrsTransportDiagnostics("test", secrets=("memory-only",), runtime_dir=tmp_path),
        update,
        radio_factory=radio_factory,
        decoder_factory=lambda: FakeCodec(bytes(1280)),  # type: ignore[arg-type]
        encoder_factory=lambda: FakeCodec(b""),  # type: ignore[arg-type]
        rx_resampler_factory=lambda: FakeResampler(b"r" * YANDEX_BLOCK_BYTES),  # type: ignore[arg-type]
        tx_resampler_factory=lambda: FakeResampler(bytes(1280 * 2 + 200)),  # type: ignore[arg-type]
        clock=clock,
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
    assert queued[-1] == RealtimeInputTransmissionCompleted("srs-ptt-000001")
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
