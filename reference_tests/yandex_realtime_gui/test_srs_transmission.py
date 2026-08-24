from __future__ import annotations

import threading

from srs_protocol import Frequency, VoicePacket
from srs_transmission import (
    PacketDecision,
    TransmissionTracker,
    TxPacer,
    split_tx_pcm,
)

OWN = "OOOOOOOOOOOOOOOOOOOOOO"
HUMAN = "HHHHHHHHHHHHHHHHHHHHHH"
SECOND = "SSSSSSSSSSSSSSSSSSSSSS"


def voice(origin: str = HUMAN, packet_id: int = 1, *, hz: float = 251_000_000.0, mod: int = 0,
          current: str | None = None) -> VoicePacket:
    return VoicePacket(
        audio=b"opus",
        frequencies=(Frequency(hz, mod, 0),),
        unit_id=1,
        packet_id=packet_id,
        retransmission_count=0,
        original_client_guid=origin,
        current_sender_guid=current or origin,
    )


def tracker() -> TransmissionTracker:
    return TransmissionTracker(OWN, 251_000_000.0, 0)


def test_one_active_origin_duplicate_old_gap_collision_and_boundary() -> None:
    item = tracker()
    assert item.accept(voice(packet_id=10), 1.0) is PacketDecision.ACCEPTED
    assert item.counters.transmissions_started == 1
    assert item.accept(voice(packet_id=10), 1.04) is PacketDecision.DUPLICATE
    assert item.accept(voice(packet_id=9), 1.08) is PacketDecision.OUT_OF_ORDER
    assert item.accept(voice(packet_id=13), 1.12) is PacketDecision.ACCEPTED
    assert item.counters.sequence_gaps == 2
    assert item.accept(voice(SECOND, 1), 1.16) is PacketDecision.COLLISION
    assert item.expire(1.519) is None
    assert item.expire(1.520) == HUMAN
    assert item.counters.transmissions_completed == 1
    assert item.accept(voice(SECOND, 1), 1.53) is PacketDecision.ACCEPTED


def test_wrong_channel_self_origin_relay_self_and_bot_tx_collision() -> None:
    item = tracker()
    assert item.accept(voice(hz=250_000_000.0), 0.0) is PacketDecision.WRONG_CHANNEL
    assert item.accept(voice(mod=1), 0.0) is PacketDecision.WRONG_CHANNEL
    assert item.accept(voice(OWN), 0.0) is PacketDecision.SELF
    assert item.accept(voice(HUMAN, current=OWN), 0.0) is PacketDecision.SELF
    item.bot_tx_active = True
    assert item.accept(voice(HUMAN), 0.0) is PacketDecision.BOT_TX_COLLISION
    assert item.counters.self_packets_dropped == 2
    assert item.counters.collisions == 1


def test_busy_channel_requires_400_ms_end_plus_250_ms_guard() -> None:
    item = tracker()
    item.accept(voice(), 10.0)
    assert not item.channel_clear(10.399)
    assert not item.channel_clear(10.649)
    assert item.channel_clear(10.650)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_tx_pacer_uses_absolute_40_ms_deadlines_without_drift() -> None:
    clock = FakeClock()
    sent: list[tuple[bytes, float]] = []
    report = TxPacer(clock=clock, sleep=clock.sleep).send(
        [b"a", b"b", b"c", b"d"],
        lambda frame, now: sent.append((frame, now)),
        threading.Event(),
    )
    assert [round(at - 100.0, 3) for _, at in sent] == [0.0, 0.04, 0.08, 0.12]
    assert report.scheduled_frames == report.sent_frames == 4
    assert report.max_jitter_ms == 0.0
    assert report.cumulative_drift_ms == 0.0


def test_tx_pacer_stop_and_one_final_padding_only() -> None:
    frames, padding = split_tx_pcm(bytes(1280 * 2 + 200))
    assert [len(frame) for frame in frames] == [1280, 1280, 1280]
    assert padding == 540
    assert frames[0] == bytes(1280)
    assert frames[1] == bytes(1280)
    stop = threading.Event()
    stop.set()
    report = TxPacer().send(frames, lambda *_: None, stop)
    assert report.sent_frames == 0
