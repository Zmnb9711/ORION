from __future__ import annotations

import threading
import time

import pytest

from orion.full_voice_srs import FullVoiceSrsEndpoint
from orion.full_voice_capture import RadioTurnEventKind
from orion.bounded_radio_stream import BoundedPcmStream
from orion.srs_diagnostics import SrsTransportDiagnostics
from orion.srs_protocol import VoicePacket, Frequency, encode_voice_packet, decode_voice_packet
from orion.srs_radio_transport import SrsRadioConfig
from orion.srs_resampler import StreamingPcm16Resampler
from orion.srs_tx_state import SrsTxStateSnapshot
from test_yandex_srs_live_core import FakeCodec, FakeRadio, FakeResampler, human_packet, HUMAN, ORION


def build(tmp_path):
    endpoint = FullVoiceSrsEndpoint(
        SrsRadioConfig(eam_password="test"), threading.Event(),
        SrsTransportDiagnostics("full-test", runtime_dir=tmp_path), lambda **_: None,
        radio_factory=lambda _config, callback, _events: FakeRadio(callback),
        decoder_factory=lambda: FakeCodec(bytes(1280)),
        encoder_factory=lambda: FakeCodec(b""),
        rx_resampler_factory=lambda: FakeResampler(b"must-not-be-used"),
        tx_resampler_factory=lambda: StreamingPcm16Resampler(44100, 16000),
    )
    endpoint.expected_origin = HUMAN
    endpoint.connect_radio()
    return endpoint


def snap(at, sending): return SrsTxStateSnapshot(sending, 1, 0, at, "test")


def test_native_rx_no_gap_eou_no_realtime_resample_self_rejected(tmp_path):
    endpoint = build(tmp_path)
    try:
        now = time.monotonic()
        endpoint.capture.snapshot(snap(now, False))
        endpoint.capture.snapshot(snap(now + .1, True))
        endpoint._on_radio_datagram(human_packet())
        endpoint.capture.tick(now + 2)
        assert endpoint.tracker.active_origin_guid == HUMAN
        assert endpoint.input_queue.empty()
        events = list(endpoint.turn_events.queue)
        assert [e.kind for e in events] == [RadioTurnEventKind.START, RadioTurnEventKind.PCM]
        assert events[-1].pcm == bytes(1280)
        self_packet = VoicePacket(audio=b"self", frequencies=(Frequency(251000000, 0),), unit_id=1, packet_id=20,
                                  retransmission_count=0, original_client_guid=ORION, current_sender_guid=ORION)
        endpoint._on_radio_datagram(encode_voice_packet(self_packet))
        assert endpoint.tracker.counters.self_packets_dropped == 1
        endpoint.capture.snapshot(snap(now + 2.1, False))
        endpoint.capture.tick(now + 2.2)
        assert endpoint.tracker.active_origin_guid is None
        assert list(endpoint.turn_events.queue)[-1].kind is RadioTurnEventKind.END
    finally: endpoint.stop()


def test_other_origin_and_queue_overflow_fail_closed(tmp_path):
    endpoint = build(tmp_path)
    try:
        endpoint.expected_origin = "unexpected"
        endpoint._on_radio_datagram(human_packet())
        assert endpoint.stop_event.is_set() and not endpoint.radio.sent
    finally: endpoint.stop()


def test_stream_tx_pacing_completion_and_no_second_identity(tmp_path):
    endpoint = build(tmp_path)
    try:
        now = time.monotonic()
        endpoint.capture.snapshot(snap(now - 1, False))
        endpoint.capture.snapshot(snap(now - .9, True))
        endpoint.capture.snapshot(snap(now - .5, False))
        endpoint.capture.tick(now)
        stream = BoundedPcmStream()
        stream.feed(bytes(3528 * 5)); stream.finish()
        result = endpoint.transmit_srs_stream("p7c-" + "a" * 32, stream, 2)
        assert result.frame_count >= 5
        assert result.duration_ms >= (result.frame_count - 1) * 39
        assert len(endpoint.radio.sent) == result.frame_count
        assert endpoint.tx_marks.get("underrun_frames", 0) == 0
        packets = [decode_voice_packet(raw) for raw in endpoint.radio.sent]
        assert [p.packet_id for p in packets] == list(range(1, len(packets) + 1))
        assert all(p.frequencies[0].hz == 251000000 for p in packets)
        assert all(p.original_client_guid == ORION for p in packets)
    finally: endpoint.stop()


@pytest.mark.parametrize("mode", ["held", "cancelled", "expired", "underrun"])
def test_stream_tx_fails_closed(tmp_path, mode):
    endpoint = build(tmp_path)
    try:
        now = time.monotonic()
        endpoint.capture.snapshot(snap(now - 1, False))
        endpoint.capture.snapshot(snap(now - .9, True))
        if mode != "held":
            endpoint.capture.snapshot(snap(now - .5, False)); endpoint.capture.tick(now)
        stream = BoundedPcmStream()
        stream.feed(bytes(10584))
        if mode != "underrun": stream.finish()
        if mode == "cancelled": stream.abort()
        if mode == "expired": endpoint.response_valid_until = now - 1
        with pytest.raises(RuntimeError): endpoint.transmit_srs_stream("test", stream, 2)
        if mode != "underrun": assert not endpoint.radio.sent
        assert not endpoint.tracker.bot_tx_active
    finally: endpoint.stop()
