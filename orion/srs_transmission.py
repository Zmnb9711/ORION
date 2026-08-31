"""SRS v0.1 RX arbitration and absolute-deadline TX pacing."""

from __future__ import annotations

import queue
import statistics
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Generic, Iterable, TypeVar

from orion.srs_protocol import VoicePacket, is_target_frequency

RX_END_GAP_SECONDS = 0.400
TX_GUARD_SECONDS = 0.250
TX_FRAME_SECONDS = 0.040


class PacketDecision(StrEnum):
    ACCEPTED = "accepted"
    WRONG_CHANNEL = "wrong_channel"
    SELF = "self"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    COLLISION = "collision"
    BOT_TX_COLLISION = "bot_tx_collision"


@dataclass(slots=True)
class TransmissionCounters:
    transmissions_started: int = 0
    transmissions_completed: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    sequence_gaps: int = 0
    collisions: int = 0
    bot_tx_collisions: int = 0
    self_packets_dropped: int = 0
    wrong_channel: int = 0


@dataclass(slots=True)
class TransmissionTracker:
    own_client_guid: str
    frequency_hz: float
    modulation: int
    counters: TransmissionCounters = field(default_factory=TransmissionCounters)
    active_origin_guid: str | None = None
    active_started_at: float | None = None
    last_human_packet_at: float | None = None
    active_packet_count: int = 0
    bot_tx_active: bool = False
    _last_packet_ids: dict[tuple[str, int], int] = field(default_factory=dict)

    def expire(self, now: float) -> str | None:
        if (
            self.active_origin_guid is not None
            and self.last_human_packet_at is not None
            and now - self.last_human_packet_at >= RX_END_GAP_SECONDS - 1e-9
        ):
            completed = self.active_origin_guid
            self.active_origin_guid = None
            self.active_started_at = None
            self.active_packet_count = 0
            self.counters.transmissions_completed += 1
            return completed
        return None

    def accept(
        self,
        packet: VoicePacket,
        now: float,
        *,
        expire_on_quiescence: bool = True,
    ) -> PacketDecision:
        if expire_on_quiescence:
            self.expire(now)
        if not is_target_frequency(packet, self.frequency_hz, self.modulation):
            self.counters.wrong_channel += 1
            return PacketDecision.WRONG_CHANNEL
        if (
            packet.original_client_guid == self.own_client_guid
            or packet.current_sender_guid == self.own_client_guid
        ):
            self.counters.self_packets_dropped += 1
            return PacketDecision.SELF
        if self.bot_tx_active:
            self.counters.collisions += 1
            self.counters.bot_tx_collisions += 1
            return PacketDecision.BOT_TX_COLLISION
        if self.active_origin_guid is not None and packet.original_client_guid != self.active_origin_guid:
            self.counters.collisions += 1
            return PacketDecision.COLLISION

        key = (packet.original_client_guid, int(self.frequency_hz))
        previous = self._last_packet_ids.get(key)
        if previous is not None:
            if packet.packet_id == previous:
                self.counters.duplicates += 1
                return PacketDecision.DUPLICATE
            if packet.packet_id < previous:
                self.counters.out_of_order += 1
                return PacketDecision.OUT_OF_ORDER
            if packet.packet_id > previous + 1:
                self.counters.sequence_gaps += packet.packet_id - previous - 1
        self._last_packet_ids[key] = packet.packet_id

        if self.active_origin_guid is None:
            self.active_origin_guid = packet.original_client_guid
            self.active_started_at = now
            self.active_packet_count = 0
            self.counters.transmissions_started += 1
        self.active_packet_count += 1
        self.last_human_packet_at = now
        return PacketDecision.ACCEPTED

    def complete_active(self) -> str | None:
        """Complete packet accounting from an authoritative external boundary."""

        completed = self.active_origin_guid
        if completed is None:
            return None
        self.active_origin_guid = None
        self.active_started_at = None
        self.active_packet_count = 0
        self.counters.transmissions_completed += 1
        return completed

    def discard_active(self) -> str | None:
        """Discard an unconfirmed packet candidate without inventing a TX end."""

        discarded = self.active_origin_guid
        self.active_origin_guid = None
        self.active_started_at = None
        self.active_packet_count = 0
        return discarded

    def channel_clear(self, now: float) -> bool:
        self.expire(now)
        return (
            not self.bot_tx_active
            and self.active_origin_guid is None
            and (
                self.last_human_packet_at is None
                or now - self.last_human_packet_at
                >= RX_END_GAP_SECONDS + TX_GUARD_SECONDS - 1e-9
            )
        )

    def reset(self) -> None:
        self.active_origin_guid = None
        self.active_started_at = None
        self.last_human_packet_at = None
        self.active_packet_count = 0
        self.bot_tx_active = False
        self._last_packet_ids.clear()
        self.counters = TransmissionCounters()


@dataclass(frozen=True, slots=True)
class PacingReport:
    scheduled_frames: int
    sent_frames: int
    median_jitter_ms: float | None
    max_jitter_ms: float | None
    cumulative_drift_ms: float | None


class TxPacer:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.clock = clock
        self.sleep = sleep

    def send(
        self,
        frames: Iterable[bytes],
        send_frame: Callable[[bytes, float], None],
        stop_event: threading.Event,
    ) -> PacingReport:
        materialized = tuple(frames)
        if not materialized:
            return PacingReport(0, 0, None, None, None)
        started = self.clock()
        jitters: list[float] = []
        sent = 0
        for index, frame in enumerate(materialized):
            if stop_event.is_set():
                break
            deadline = started + index * TX_FRAME_SECONDS
            remaining = deadline - self.clock()
            if remaining > 0:
                self.sleep(remaining)
            actual = self.clock()
            if stop_event.is_set():
                break
            send_frame(frame, actual)
            jitters.append((actual - deadline) * 1000)
            sent += 1
        drift = jitters[-1] if jitters else None
        return PacingReport(
            scheduled_frames=len(materialized),
            sent_frames=sent,
            median_jitter_ms=round(statistics.median(jitters), 3) if jitters else None,
            max_jitter_ms=round(max(abs(item) for item in jitters), 3) if jitters else None,
            cumulative_drift_ms=round(drift, 3) if drift is not None else None,
        )


def split_tx_pcm(pcm16le: bytes, frame_bytes: int = 1_280) -> tuple[tuple[bytes, ...], int]:
    if len(pcm16le) % 2:
        raise ValueError("TX PCM must contain complete PCM16 samples.")
    frames = [pcm16le[offset : offset + frame_bytes] for offset in range(0, len(pcm16le), frame_bytes)]
    final_padding_samples = 0
    if frames and len(frames[-1]) < frame_bytes:
        missing = frame_bytes - len(frames[-1])
        final_padding_samples = missing // 2
        frames[-1] += bytes(missing)
    return tuple(frames), final_padding_samples


T = TypeVar("T")


class OneResponseQueue(Generic[T]):
    """A hard one-response bound used by radio output."""

    def __init__(self) -> None:
        self._queue: queue.Queue[T] = queue.Queue(maxsize=1)

    def put(self, value: T) -> None:
        self._queue.put_nowait(value)

    def get(self, timeout: float | None = None) -> T:
        return self._queue.get(timeout=timeout)

    def discard(self) -> T | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    @property
    def pending(self) -> bool:
        return not self._queue.empty()
