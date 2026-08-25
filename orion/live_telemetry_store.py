from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock

from orion.models import TelemetryEnvelope


@dataclass(frozen=True, slots=True)
class LiveTelemetrySnapshot:
    telemetry: TelemetryEnvelope | None
    last_received_at: datetime | None
    source: str | None
    protocol_version: str | None
    generation: int


class LiveTelemetryStore:
    def __init__(self) -> None:
        self._latest: TelemetryEnvelope | None = None
        self._last_received_at: datetime | None = None
        self._source: str | None = None
        self._protocol_version: str | None = None
        self._generation = 0
        self._lock = RLock()

    def set(
        self,
        payload: TelemetryEnvelope,
        *,
        received_at: datetime | None = None,
    ) -> None:
        timestamp = self._normalize_timestamp(received_at)
        with self._lock:
            self._latest = payload.model_copy(deep=True)
            self._last_received_at = timestamp
            self._source = payload.source
            self._protocol_version = payload.protocol_version
            self._generation += 1

    def observe_heartbeat(
        self,
        *,
        source: str = "dcs-export",
        protocol_version: str = "0.3",
        received_at: datetime | None = None,
    ) -> None:
        """Record a live Export bridge with no current player aircraft."""
        timestamp = self._normalize_timestamp(received_at)
        with self._lock:
            self._latest = None
            self._last_received_at = timestamp
            self._source = source
            self._protocol_version = protocol_version
            self._generation += 1

    def get(self) -> TelemetryEnvelope | None:
        with self._lock:
            return self._latest.model_copy(deep=True) if self._latest is not None else None

    def snapshot(self) -> LiveTelemetrySnapshot:
        with self._lock:
            return LiveTelemetrySnapshot(
                telemetry=(
                    self._latest.model_copy(deep=True)
                    if self._latest is not None
                    else None
                ),
                last_received_at=self._last_received_at,
                source=self._source,
                protocol_version=self._protocol_version,
                generation=self._generation,
            )

    def clear(self) -> None:
        with self._lock:
            self._latest = None
            self._last_received_at = None
            self._source = None
            self._protocol_version = None
            self._generation += 1

    @staticmethod
    def _normalize_timestamp(value: datetime | None) -> datetime:
        timestamp = value or datetime.now(UTC)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp


live_telemetry = LiveTelemetryStore()
