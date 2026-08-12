from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock

from orion.models import TelemetryEnvelope


@dataclass(frozen=True)
class TelemetryHandshakeSnapshot:
    connected: bool
    aircraft_type: str | None
    source: str | None
    protocol_version: str | None
    last_received_at: datetime | None
    packet_count: int
    packet_rate_hz: float
    age_seconds: float | None


class TelemetryHandshake:
    def __init__(self, stale_after_seconds: float = 5.0, rate_window_seconds: float = 5.0) -> None:
        self._stale_after = timedelta(seconds=stale_after_seconds)
        self._rate_window = timedelta(seconds=rate_window_seconds)
        self._last_received_at: datetime | None = None
        self._aircraft_type: str | None = None
        self._source: str | None = None
        self._protocol_version: str | None = None
        self._packet_count = 0
        self._received_times: deque[datetime] = deque()
        self._lock = RLock()

    def observe(self, payload: TelemetryEnvelope, *, received_at: datetime | None = None) -> None:
        timestamp = self._normalize_timestamp(received_at)
        with self._lock:
            self._last_received_at = timestamp
            self._aircraft_type = payload.state.aircraft_type
            self._source = payload.source
            self._protocol_version = payload.protocol_version
            self._packet_count += 1
            self._received_times.append(timestamp)
            self._prune(timestamp)

    def observe_heartbeat(
        self,
        *,
        source: str = "dcs-export",
        protocol_version: str = "0.2",
        received_at: datetime | None = None,
    ) -> None:
        """Record that the DCS Export bridge is alive even when no aircraft state is available."""
        timestamp = self._normalize_timestamp(received_at)
        with self._lock:
            self._last_received_at = timestamp
            self._aircraft_type = None
            self._source = source
            self._protocol_version = protocol_version
            self._prune(timestamp)

    def snapshot(self, *, now: datetime | None = None) -> TelemetryHandshakeSnapshot:
        current = self._normalize_timestamp(now)
        with self._lock:
            self._prune(current)
            last = self._last_received_at
            age = None if last is None else max(0.0, (current - last).total_seconds())
            connected = last is not None and current - last <= self._stale_after
            return TelemetryHandshakeSnapshot(
                connected=connected,
                aircraft_type=self._aircraft_type if connected else None,
                source=self._source if connected else None,
                protocol_version=self._protocol_version if connected else None,
                last_received_at=last,
                packet_count=self._packet_count,
                packet_rate_hz=self._rate_hz(),
                age_seconds=age,
            )

    def reset(self) -> None:
        with self._lock:
            self._last_received_at = None
            self._aircraft_type = None
            self._source = None
            self._protocol_version = None
            self._packet_count = 0
            self._received_times.clear()

    @staticmethod
    def _normalize_timestamp(value: datetime | None) -> datetime:
        timestamp = value or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp

    def _prune(self, now: datetime) -> None:
        threshold = now - self._rate_window
        while self._received_times and self._received_times[0] < threshold:
            self._received_times.popleft()

    def _rate_hz(self) -> float:
        if len(self._received_times) < 2:
            return 0.0
        span = (self._received_times[-1] - self._received_times[0]).total_seconds()
        if span <= 0:
            return 0.0
        return round((len(self._received_times) - 1) / span, 2)


telemetry_handshake = TelemetryHandshake()
