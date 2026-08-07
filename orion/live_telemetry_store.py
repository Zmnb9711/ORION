from __future__ import annotations

from threading import RLock

from orion.models import TelemetryEnvelope


class LiveTelemetryStore:
    def __init__(self) -> None:
        self._latest: TelemetryEnvelope | None = None
        self._lock = RLock()

    def set(self, payload: TelemetryEnvelope) -> None:
        with self._lock:
            self._latest = payload.model_copy(deep=True)

    def get(self) -> TelemetryEnvelope | None:
        with self._lock:
            return self._latest.model_copy(deep=True) if self._latest is not None else None

    def clear(self) -> None:
        with self._lock:
            self._latest = None


live_telemetry = LiveTelemetryStore()
