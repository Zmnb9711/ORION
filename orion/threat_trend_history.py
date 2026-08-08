from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from pydantic import BaseModel, Field


class SustainedThreatTrend(StrEnum):
    CLOSING = "closing"
    STABLE = "stable"
    DIVERGING = "diverging"
    INSUFFICIENT_DATA = "insufficient_data"


class ThreatTrendHistory(BaseModel):
    trend: SustainedThreatTrend = SustainedThreatTrend.INSUFFICIENT_DATA
    samples: int = Field(default=0, ge=0)
    range_change_nm: float | None = None
    sustained: bool = False


@dataclass(frozen=True)
class _RangeSample:
    range_nm: float


class ThreatTrendTracker:
    """Track short range histories, isolated to one mission at a time."""

    def __init__(self, max_samples: int = 5, min_samples: int = 3, noise_nm: float = 0.5) -> None:
        self._max_samples = max(3, max_samples)
        self._min_samples = max(3, min(min_samples, self._max_samples))
        self._noise_nm = max(0.0, noise_nm)
        self._history: dict[str, deque[_RangeSample]] = {}
        self._mission_id: str | None = None
        self._lock = RLock()

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._mission_id = None

    def observe(self, unit_id: str, range_nm: float, *, mission_id: str | None = None) -> ThreatTrendHistory:
        with self._lock:
            self._bind_mission(mission_id)
            samples = self._history.setdefault(unit_id, deque(maxlen=self._max_samples))
            samples.append(_RangeSample(range_nm=range_nm))
            return self._summarize(samples)

    def retain(self, unit_ids: set[str], *, mission_id: str | None = None) -> None:
        with self._lock:
            self._bind_mission(mission_id)
            for stale in list(self._history):
                if stale not in unit_ids:
                    del self._history[stale]

    def _bind_mission(self, mission_id: str | None) -> None:
        if mission_id is None:
            return
        if self._mission_id is None:
            self._mission_id = mission_id
            return
        if mission_id != self._mission_id:
            self._history.clear()
            self._mission_id = mission_id

    def _summarize(self, samples: deque[_RangeSample]) -> ThreatTrendHistory:
        count = len(samples)
        if count < self._min_samples:
            return ThreatTrendHistory(samples=count)

        ranges = [item.range_nm for item in samples]
        net = ranges[-1] - ranges[0]
        deltas = [b - a for a, b in zip(ranges, ranges[1:])]
        meaningful = [delta for delta in deltas if abs(delta) > self._noise_nm]
        if not meaningful:
            trend = SustainedThreatTrend.STABLE
            sustained = True
        elif all(delta < 0 for delta in meaningful) and net < -self._noise_nm:
            trend = SustainedThreatTrend.CLOSING
            sustained = True
        elif all(delta > 0 for delta in meaningful) and net > self._noise_nm:
            trend = SustainedThreatTrend.DIVERGING
            sustained = True
        else:
            trend = SustainedThreatTrend.STABLE
            sustained = False

        return ThreatTrendHistory(
            trend=trend,
            samples=count,
            range_change_nm=round(net, 1),
            sustained=sustained,
        )


threat_trend_tracker = ThreatTrendTracker()
