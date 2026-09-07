"""One local SRS physical turn, with bounded packet/snapshot skew.

UDP7082 is LOCAL client evidence only, not a distributed radio/PTT protocol.
The field host injects one expected remote SRS origin from its controlled
two-client topology. Packet gaps never finish a held physical turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import threading
from typing import Callable
from uuid import UUID, uuid4

from orion.srs_tx_state import SrsTxStateSnapshot


class RadioTurnEventKind(StrEnum):
    START = "start"
    PCM = "pcm"
    END = "end"


@dataclass(frozen=True, slots=True)
class RadioTurnEvent:
    kind: RadioTurnEventKind
    identity: UUID
    timestamp: float
    pcm: bytes = field(default=b"", repr=False)


class PhysicalRadioTurn:
    """Thread-safe bounded physical ownership, held until downstream release."""

    def __init__(
        self,
        emit: Callable[[RadioTurnEvent], None],
        fail: Callable[[str], None],
        *,
        radio_index: int = 1,
        skew_seconds: float = 0.5,
        drain_seconds: float = 0.08,
        max_turn_seconds: float = 30.0,
    ) -> None:
        self.emit, self.fail = emit, fail
        self.radio_index = radio_index
        self.skew_seconds = skew_seconds
        self.drain_seconds = drain_seconds
        self.max_turn_seconds = max_turn_seconds
        self._lock = threading.RLock()
        self.owner: UUID | None = None
        self._snapshot: SrsTxStateSnapshot | None = None
        self._started = 0.0
        self._end: float | None = None
        self._ended = False
        self._failed = False
        self._candidate: list[tuple[bytes, float]] = []
        self._candidate_bytes = 0

    def snapshot(self, value: SrsTxStateSnapshot) -> None:
        with self._lock:
            if self._failed:
                return
            previous = self._snapshot
            self._snapshot = value
            if value.is_sending and (
                value.sending_on != self.radio_index or value.is_encrypted != 0
            ):
                self.abort("unexpected_physical_radio")
                return
            if value.is_sending and (previous is None or not previous.is_sending):
                if previous is None or self.owner is not None:
                    self.abort("physical_turn_busy_or_missing_idle")
                    return
                self.owner = uuid4()
                self._started = value.received_at
                self._end = None
                self._ended = False
                self.emit(RadioTurnEvent(RadioTurnEventKind.START, self.owner, self._started))
                for pcm, at in self._candidate:
                    if self._started - at > self.skew_seconds:
                        self.abort("unconfirmed_rx_candidate")
                        return
                    self.emit(RadioTurnEvent(RadioTurnEventKind.PCM, self.owner, at, pcm))
                self._candidate.clear()
                self._candidate_bytes = 0
            elif not value.is_sending and previous is not None and previous.is_sending:
                if self.owner is None or self._end is not None:
                    self.abort("physical_end_without_owner")
                    return
                self._end = value.received_at

    def pcm(self, pcm: bytes, at: float) -> None:
        with self._lock:
            if self._failed:
                return
            if not pcm or len(pcm) % 2 or len(pcm) > 6400:
                self.abort("invalid_decoded_pcm")
                return
            if self.owner is None:
                self._candidate_bytes += len(pcm)
                if self._candidate_bytes > 32_000 * self.skew_seconds:
                    self.abort("rx_candidate_overflow")
                    return
                self._candidate.append((pcm, at))
            elif self._ended or (self._end is not None and at > self._end + self.drain_seconds):
                self.abort("rx_after_physical_barrier")
            else:
                self.emit(RadioTurnEvent(RadioTurnEventKind.PCM, self.owner, at, pcm))

    def tick(self, now: float) -> None:
        with self._lock:
            if self._failed:
                return
            if self._candidate and now - self._candidate[0][1] > self.skew_seconds:
                self.abort("rx_without_physical_ptt")
                return
            if self.owner is None:
                return
            if self._end is None and now - self._started > self.max_turn_seconds:
                self.abort("physical_turn_timeout")
            elif self._end is not None and not self._ended and now >= self._end + self.drain_seconds:
                self._ended = True
                self.emit(RadioTurnEvent(RadioTurnEventKind.END, self.owner, self._end))

    def release(self, identity: UUID) -> None:
        with self._lock:
            if self._failed or identity != self.owner or not self._ended:
                self.abort("physical_release_mismatch")
                return
            self.owner = None

    def abort(self, code: str) -> None:
        with self._lock:
            if not self._failed:
                self._failed = True
                self._candidate.clear()
                self._candidate_bytes = 0
                self.fail(code)

    def tx_permitted(self) -> bool:
        with self._lock:
            return (
                not self._failed and self.owner is not None and self._ended
                and self._snapshot is not None and not self._snapshot.is_sending
            )
