"""Provider-neutral realtime turn boundaries and bounded latency markers."""

from __future__ import annotations

import math
import statistics
import time
from collections import deque
from dataclasses import dataclass
from threading import RLock
from typing import Callable


@dataclass(frozen=True, slots=True)
class RealtimeFirstAudio:
    turn_id: str
    response_id: str
    response_created_to_first_audio_ms: float
    speech_stopped_to_first_audio_ms: float | None


@dataclass(frozen=True, slots=True)
class RealtimeLatencySummary:
    sample_count: int
    latest_ms: float | None
    median_ms: float | None
    p90_ms: float | None
    maximum_ms: float | None


class RealtimeInteractionState:
    """Correlate provider events without retaining transcript or audio content."""

    def __init__(
        self,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        latency_window: int = 32,
    ) -> None:
        if latency_window <= 0:
            raise ValueError("Realtime latency window must be positive")
        self._clock_ns = clock_ns
        self._lock = RLock()
        self._turn_sequence = 0
        self._current_turn_id: str | None = None
        self._user_speaking = False
        self._speech_stopped_ns: dict[str, int] = {}
        self._response_turns: dict[str, str] = {}
        self._response_created_ns: dict[str, int] = {}
        self._first_audio_responses: set[str] = set()
        self._latencies_ms: deque[float] = deque(maxlen=latency_window)

    @property
    def safe_to_refresh(self) -> bool:
        with self._lock:
            return (
                not self._user_speaking
                and self._current_turn_id is None
                and not self._response_turns
            )

    def speech_started(self) -> str:
        with self._lock:
            self._turn_sequence += 1
            self._current_turn_id = f"turn_{self._turn_sequence:03d}"
            self._user_speaking = True
            return self._current_turn_id

    def speech_stopped(self) -> str | None:
        now = self._clock_ns()
        with self._lock:
            self._user_speaking = False
            turn_id = self._current_turn_id
            if turn_id is not None:
                self._speech_stopped_ns[turn_id] = now
            return turn_id

    def current_turn_id(self) -> str | None:
        with self._lock:
            return self._current_turn_id

    def response_started(self, response_id: str) -> str:
        now = self._clock_ns()
        with self._lock:
            turn_id = self._current_turn_id
            if turn_id is None:
                self._turn_sequence += 1
                turn_id = f"turn_{self._turn_sequence:03d}"
                self._current_turn_id = turn_id
            self._response_turns[response_id] = turn_id
            self._response_created_ns[response_id] = now
            return turn_id

    def first_audio(self, response_id: str) -> RealtimeFirstAudio | None:
        now = self._clock_ns()
        with self._lock:
            if response_id in self._first_audio_responses:
                return None
            created_ns = self._response_created_ns.get(response_id)
            turn_id = self._response_turns.get(response_id)
            if created_ns is None or turn_id is None:
                return None
            self._first_audio_responses.add(response_id)
            response_ms = (now - created_ns) / 1_000_000
            stopped_ns = self._speech_stopped_ns.get(turn_id)
            speech_ms = (
                None if stopped_ns is None else (now - stopped_ns) / 1_000_000
            )
            self._latencies_ms.append(response_ms)
            return RealtimeFirstAudio(
                turn_id=turn_id,
                response_id=response_id,
                response_created_to_first_audio_ms=response_ms,
                speech_stopped_to_first_audio_ms=speech_ms,
            )

    def response_done(self, response_id: str) -> str | None:
        with self._lock:
            turn_id = self._response_turns.pop(response_id, None)
            self._response_created_ns.pop(response_id, None)
            self._first_audio_responses.discard(response_id)
            if (
                turn_id is not None
                and turn_id == self._current_turn_id
                and turn_id not in self._response_turns.values()
            ):
                self._current_turn_id = None
                self._speech_stopped_ns.pop(turn_id, None)
            return turn_id

    def latency_summary(self) -> RealtimeLatencySummary:
        with self._lock:
            values = tuple(self._latencies_ms)
        if not values:
            return RealtimeLatencySummary(0, None, None, None, None)
        ordered = sorted(values)
        p90_index = max(0, math.ceil(0.9 * len(ordered)) - 1)
        return RealtimeLatencySummary(
            sample_count=len(values),
            latest_ms=values[-1],
            median_ms=statistics.median(values),
            p90_ms=ordered[p90_index],
            maximum_ms=max(values),
        )
