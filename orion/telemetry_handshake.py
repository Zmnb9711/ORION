from __future__ import annotations

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


class TelemetryHandshake:
    def __init__(self, stale_after_seconds: float = 5.0) -> None:
        self._stale_after = timedelta(seconds=stale_after_seconds)
        self._last_received_at: datetime | None = None
        self._aircraft_type: str | None = None
        self._source: str | None = None
        self._protocol_version: str | None = None
        self._packet_count = 0
        self._lock = RLock()

    def observe(self, payload: TelemetryEnvelope, *, received_at: datetime | None = None) -> None:
        timestamp = received_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        with self._lock:
            self._last_received_at = timestamp
            self._aircraft_type = payload.state.aircraft_type
            self._source = payload.source
            self._protocol_version = payload.protocol_version
            self._packet_count += 1

    def snapshot(self, *, now: datetime | None = None) -> TelemetryHandshakeSnapshot:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        with self._lock:
            last = self._last_received_at
            connected = last is not None and current - last <= self._stale_after
            return TelemetryHandshakeSnapshot(
                connected=connected,
                aircraft_type=self._aircraft_type if connected else None,
                source=self._source if connected else None,
                protocol_version=self._protocol_version if connected else None,
                last_received_at=last,
                packet_count=self._packet_count,
            )

    def reset(self) -> None:
        with self._lock:
            self._last_received_at = None
            self._aircraft_type = None
            self._source = None
            self._protocol_version = None
            self._packet_count = 0


telemetry_handshake = TelemetryHandshake()
