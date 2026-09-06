"""Provider-neutral, single-consumer PCM stream with explicit terminal states."""

from __future__ import annotations

import threading
import time
from uuid import uuid4


class BoundedPcmStream:
    def __init__(self, *, capacity: int = 176_400, limit: int = 2_646_000) -> None:
        if capacity < 10584 or capacity % 2 or limit < capacity:
            raise ValueError("invalid_stream_bounds")
        self._identity = uuid4().hex
        self.capacity, self.limit = capacity, limit
        self._condition = threading.Condition()
        self._buffer = bytearray()
        self._total = 0
        self._ended = False
        self._failure: str | None = None
        self.high_water = 0

    @property
    def identity(self) -> str:
        return self._identity

    def feed(self, pcm: bytes, timeout: float = 2.0) -> None:
        if not pcm or len(pcm) % 2:
            self.abort("invalid_stream_pcm")
            raise ValueError("invalid_stream_pcm")
        deadline = time.monotonic() + timeout
        with self._condition:
            if self._ended or self._failure or self._total + len(pcm) > self.limit:
                self.abort("stream_closed_or_excessive")
                raise RuntimeError("stream_closed_or_excessive")
            self._total += len(pcm)
            offset = 0
            while offset < len(pcm):
                if self._failure:
                    raise RuntimeError(self._failure)
                count = min(self.capacity - len(self._buffer), len(pcm) - offset)
                if count:
                    self._buffer.extend(pcm[offset:offset + count])
                    offset += count
                    self.high_water = max(self.high_water, len(self._buffer))
                    deadline = time.monotonic() + timeout
                    self._condition.notify_all()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.abort("stream_backpressure_timeout")
                        raise TimeoutError("stream_backpressure_timeout")
                    self._condition.wait(remaining)

    def finish(self) -> None:
        with self._condition:
            if not self._total:
                self.abort("empty_stream")
                return
            self._ended = True
            self._condition.notify_all()

    def abort(self, code: str = "stream_cancelled") -> None:
        with self._condition:
            self._failure = code
            self._buffer.clear()
            self._condition.notify_all()

    def wait_prebuffer(self, count: int = 10584, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self._buffer) < count and not self._ended and not self._failure:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("stream_prebuffer_timeout")
                self._condition.wait(min(remaining, .1))
            if self._failure:
                raise RuntimeError(self._failure)

    def read(self, count: int) -> tuple[bytes, bool]:
        with self._condition:
            if self._failure:
                raise RuntimeError(self._failure)
            size = min(count, len(self._buffer))
            data = bytes(self._buffer[:size])
            del self._buffer[:size]
            self._condition.notify_all()
            return data, self._ended and not self._buffer
