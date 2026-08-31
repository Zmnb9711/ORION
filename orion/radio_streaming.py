"""Provider-neutral bounded PCM streaming contracts for radio presentation."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


class StreamingPcmState(StrEnum):
    OPEN = "open"
    END_OF_STREAM = "end_of_stream"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class StreamingPcmEvent:
    """One provider-neutral PCM event; provider protobufs never cross this seam."""

    response_id: str
    pcm: bytes
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    chunk_index: int
    end_of_stream: bool = False
    error: str | None = None
    cancelled: bool = False

    def __post_init__(self) -> None:
        if not self.response_id or len(self.response_id) > 200:
            raise ValueError("Streaming PCM response ID is invalid")
        if self.sample_rate_hz < 8_000 or self.sample_rate_hz > 192_000:
            raise ValueError("Streaming PCM sample rate is invalid")
        if self.channels != 1 or self.sample_width_bytes != 2:
            raise ValueError("Streaming radio PCM must be mono signed PCM16LE")
        if self.chunk_index < 0:
            raise ValueError("Streaming PCM chunk index cannot be negative")
        terminal_flags = int(self.end_of_stream) + int(self.error is not None) + int(
            self.cancelled
        )
        if terminal_flags > 1:
            raise ValueError("Streaming PCM event has conflicting terminal states")
        if terminal_flags and self.pcm:
            raise ValueError("Terminal streaming PCM events cannot carry audio")
        if not terminal_flags and not self.pcm:
            raise ValueError("Streaming PCM chunk cannot be empty")
        if self.error is not None and (not self.error.strip() or len(self.error) > 300):
            raise ValueError("Streaming PCM error must be a bounded safe message")


class Pcm16ChunkAligner:
    """Carry one split byte across arbitrary provider chunk boundaries."""

    def __init__(self) -> None:
        self._carry = b""

    def push(self, pcm: bytes) -> bytes:
        combined = self._carry + bytes(pcm)
        aligned_length = len(combined) - (len(combined) % 2)
        self._carry = combined[aligned_length:]
        return combined[:aligned_length]

    def finish(self) -> bytes:
        if self._carry:
            raise ValueError("SpeechKit stream ended with an incomplete PCM16 sample")
        return b""


@dataclass(frozen=True, slots=True)
class StreamingPcmRead:
    data: bytes = b""
    state: StreamingPcmState = StreamingPcmState.OPEN
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StreamingPcmSnapshot:
    state: StreamingPcmState
    buffered_bytes: int
    total_pcm_bytes: int
    max_buffered_bytes: int
    chunk_count: int
    captured_pcm: bytes | None
    pcm_sha256: str


class BoundedPcmStream:
    """Blocking cross-thread PCM queue with byte bounds and producer backpressure."""

    def __init__(
        self,
        response_id: str,
        *,
        sample_rate_hz: int,
        prebuffer_ms: int,
        max_buffer_ms: int,
        max_total_bytes: int,
        capture: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not response_id or len(response_id) > 200:
            raise ValueError("Streaming PCM response ID is invalid")
        if sample_rate_hz < 8_000 or sample_rate_hz > 192_000:
            raise ValueError("Streaming PCM sample rate is invalid")
        if prebuffer_ms <= 0 or max_buffer_ms < prebuffer_ms:
            raise ValueError("Streaming PCM buffer bounds are invalid")
        if max_total_bytes <= 0:
            raise ValueError("Streaming PCM total bound must be positive")
        bytes_per_second = sample_rate_hz * 2
        self.response_id = response_id
        self.sample_rate_hz = sample_rate_hz
        self.channels = 1
        self.sample_width_bytes = 2
        self.prebuffer_bytes = _aligned(bytes_per_second * prebuffer_ms // 1000)
        self.max_buffer_bytes = _aligned(bytes_per_second * max_buffer_ms // 1000)
        self.max_total_bytes = max_total_bytes
        self._capture_enabled = capture
        self._clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._chunks: deque[bytes] = deque()
        self._state = StreamingPcmState.OPEN
        self._error: str | None = None
        self._buffered_bytes = 0
        self._total_pcm_bytes = 0
        self._max_buffered_bytes = 0
        self._chunk_count = 0
        self._capture = bytearray()
        self._digest = hashlib.sha256()

    @property
    def prebuffer_ms(self) -> float:
        return self.prebuffer_bytes / (self.sample_rate_hz * 2) * 1000

    @property
    def max_buffer_ms(self) -> float:
        return self.max_buffer_bytes / (self.sample_rate_hz * 2) * 1000

    def feed(self, pcm: bytes, *, timeout_s: float = 35.0) -> None:
        payload = bytes(pcm)
        if not payload or len(payload) % 2:
            raise ValueError("Streaming PCM feed requires aligned non-empty PCM16")
        if len(payload) > self.max_buffer_bytes:
            raise ValueError("Streaming PCM feed exceeds the bounded buffer")
        deadline = self._clock() + timeout_s
        with self._condition:
            while (
                self._state is StreamingPcmState.OPEN
                and self._buffered_bytes + len(payload) > self.max_buffer_bytes
            ):
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise TimeoutError("Timed out applying streaming PCM backpressure")
                self._condition.wait(min(0.1, remaining))
            self._require_open_locked()
            if self._total_pcm_bytes + len(payload) > self.max_total_bytes:
                raise ValueError("Streaming PCM exceeds the bounded response limit")
            self._chunks.append(payload)
            self._buffered_bytes += len(payload)
            self._total_pcm_bytes += len(payload)
            self._chunk_count += 1
            self._max_buffered_bytes = max(
                self._max_buffered_bytes, self._buffered_bytes
            )
            self._digest.update(payload)
            if self._capture_enabled:
                self._capture.extend(payload)
            self._condition.notify_all()

    def wait_for_prebuffer(self, timeout_s: float) -> StreamingPcmSnapshot:
        deadline = self._clock() + timeout_s
        with self._condition:
            while (
                self._state is StreamingPcmState.OPEN
                and self._buffered_bytes < self.prebuffer_bytes
            ):
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for streaming PCM prebuffer")
                self._condition.wait(min(0.1, remaining))
            if self._state is StreamingPcmState.FAILED:
                raise RuntimeError(self._error or "Streaming PCM provider failed")
            if self._state is StreamingPcmState.CANCELLED:
                raise RuntimeError("Streaming PCM was cancelled")
            if not self._buffered_bytes:
                raise RuntimeError("Streaming PCM ended without audio")
            return self._snapshot_locked()

    def read(self, max_bytes: int, *, timeout_s: float = 0.0) -> StreamingPcmRead:
        if max_bytes <= 0:
            raise ValueError("Streaming PCM read bound must be positive")
        max_bytes = _aligned(max_bytes)
        deadline = self._clock() + max(0.0, timeout_s)
        with self._condition:
            while not self._chunks and self._state is StreamingPcmState.OPEN:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return StreamingPcmRead()
                self._condition.wait(min(0.05, remaining))
            if self._chunks:
                chunk = self._chunks.popleft()
                if len(chunk) > max_bytes:
                    result = chunk[:max_bytes]
                    self._chunks.appendleft(chunk[max_bytes:])
                else:
                    result = chunk
                self._buffered_bytes -= len(result)
                self._condition.notify_all()
                return StreamingPcmRead(data=result)
            return StreamingPcmRead(state=self._state, error=self._error)

    def finish(self) -> None:
        with self._condition:
            self._require_open_locked()
            self._state = StreamingPcmState.END_OF_STREAM
            self._condition.notify_all()

    def fail(self, message: str) -> None:
        safe = " ".join(str(message).split())[:300] or "Streaming PCM provider failed"
        with self._condition:
            if self._state is not StreamingPcmState.OPEN:
                return
            self._chunks.clear()
            self._buffered_bytes = 0
            self._error = safe
            self._state = StreamingPcmState.FAILED
            self._condition.notify_all()

    def cancel(self) -> None:
        with self._condition:
            if self._state in {
                StreamingPcmState.FAILED,
                StreamingPcmState.CANCELLED,
            }:
                return
            self._chunks.clear()
            self._buffered_bytes = 0
            self._state = StreamingPcmState.CANCELLED
            self._condition.notify_all()

    def snapshot(self) -> StreamingPcmSnapshot:
        with self._condition:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> StreamingPcmSnapshot:
        return StreamingPcmSnapshot(
            state=self._state,
            buffered_bytes=self._buffered_bytes,
            total_pcm_bytes=self._total_pcm_bytes,
            max_buffered_bytes=self._max_buffered_bytes,
            chunk_count=self._chunk_count,
            captured_pcm=(bytes(self._capture) if self._capture_enabled else None),
            pcm_sha256=self._digest.hexdigest(),
        )

    def _require_open_locked(self) -> None:
        if self._state is not StreamingPcmState.OPEN:
            raise RuntimeError(f"Streaming PCM is already {self._state.value}")


def _aligned(value: int) -> int:
    return value - (value % 2)
