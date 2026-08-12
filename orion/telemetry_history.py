from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import deque
from datetime import UTC, datetime
from threading import RLock

from pydantic import BaseModel, Field

from orion.models import TelemetryEnvelope


DEFAULT_HISTORY_PACKETS = 5000


class TelemetryPacketSample(BaseModel):
    received_at: datetime
    payload: dict[str, object]


class TelemetryHistoryReport(BaseModel):
    capacity: int = DEFAULT_HISTORY_PACKETS
    retained_packet_count: int = 0
    total_packet_count: int = 0
    session_started_at: datetime | None = None
    last_packet_at: datetime | None = None
    last_seen_aircraft_type: str | None = None
    last_source: str | None = None
    last_protocol_version: str | None = None
    average_packet_rate_hz: float = Field(default=0.0, ge=0)
    samples: list[TelemetryPacketSample] = Field(default_factory=list)


class TelemetryHistoryRecorder:
    def __init__(self, capacity: int = DEFAULT_HISTORY_PACKETS) -> None:
        if capacity < 1:
            raise ValueError("Telemetry history capacity must be at least 1")
        self._capacity = capacity
        self._samples: deque[TelemetryPacketSample] = deque(maxlen=capacity)
        self._total_packet_count = 0
        self._session_started_at: datetime | None = None
        self._last_packet_at: datetime | None = None
        self._last_seen_aircraft_type: str | None = None
        self._last_source: str | None = None
        self._last_protocol_version: str | None = None
        self._lock = RLock()

    def observe(self, payload: TelemetryEnvelope, *, received_at: datetime | None = None) -> None:
        timestamp = _normalize_timestamp(received_at)
        sample = TelemetryPacketSample(
            received_at=timestamp,
            payload=payload.model_dump(mode="json"),
        )
        with self._lock:
            if self._session_started_at is None:
                self._session_started_at = timestamp
            self._last_packet_at = timestamp
            self._total_packet_count += 1
            self._last_seen_aircraft_type = payload.state.aircraft_type
            self._last_source = payload.source
            self._last_protocol_version = payload.protocol_version
            self._samples.append(sample)

    def report(self) -> TelemetryHistoryReport:
        with self._lock:
            average_rate = 0.0
            if (
                self._session_started_at is not None
                and self._last_packet_at is not None
                and self._total_packet_count > 1
            ):
                span = (self._last_packet_at - self._session_started_at).total_seconds()
                if span > 0:
                    average_rate = round((self._total_packet_count - 1) / span, 2)
            return TelemetryHistoryReport(
                capacity=self._capacity,
                retained_packet_count=len(self._samples),
                total_packet_count=self._total_packet_count,
                session_started_at=self._session_started_at,
                last_packet_at=self._last_packet_at,
                last_seen_aircraft_type=self._last_seen_aircraft_type,
                last_source=self._last_source,
                last_protocol_version=self._last_protocol_version,
                average_packet_rate_hz=average_rate,
                samples=list(self._samples),
            )

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._total_packet_count = 0
            self._session_started_at = None
            self._last_packet_at = None
            self._last_seen_aircraft_type = None
            self._last_source = None
            self._last_protocol_version = None


def collect_telemetry_history() -> TelemetryHistoryReport:
    if os.environ.get("ORION_PROCESS_ROLE") == "launcher":
        return _collect_telemetry_history_via_core()
    return telemetry_history_recorder.report()


def _collect_telemetry_history_via_core() -> TelemetryHistoryReport:
    base_url = os.environ.get("ORION_CORE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    request = urllib.request.Request(f"{base_url}/v1/dcs-connection/telemetry-history", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return TelemetryHistoryReport()
    return TelemetryHistoryReport.model_validate(payload)


def _normalize_timestamp(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp


telemetry_history_recorder = TelemetryHistoryRecorder()
