"""Core-owned current DCS flight context and realtime-AI projection.

The authoritative state remains the existing single-current
``LiveTelemetryStore``.  This module adds freshness semantics and a compact,
provider-neutral AI view; it does not retain telemetry history.
"""

from __future__ import annotations

import re
import time
from hashlib import sha256
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Callable

from pydantic import BaseModel, ConfigDict

from orion.aircraft_knowledge import aircraft_knowledge
from orion.live_telemetry_store import LiveTelemetryStore, live_telemetry
from orion.realtime_ai_instructions import compose_realtime_instructions


class FlightContextState(StrEnum):
    NO_DCS = "no_dcs"
    DCS_CONNECTED_NO_AIRCRAFT = "dcs_connected_no_aircraft"
    FRESH = "fresh"
    STALE = "stale"


class FlightContextSnapshot(BaseModel):
    """Credential-free, immutable view of the current authoritative state."""

    model_config = ConfigDict(frozen=True)

    state: FlightContextState
    fresh: bool = False
    generation: int = 0
    source: str | None = None
    protocol_version: str | None = None
    received_at: datetime | None = None
    age_seconds: float | None = None
    aircraft_type: str | None = None
    aircraft_display_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    altitude_agl_m: float | None = None
    heading_deg: float | None = None
    true_airspeed_mps: float | None = None
    vertical_speed_mps: float | None = None


class AiFlightContextUpdate(BaseModel):
    """Compact semantic context ready for any realtime provider."""

    model_config = ConfigDict(frozen=True)

    instructions: str
    state: FlightContextState
    fresh: bool
    generation: int
    aircraft_type: str | None = None
    aircraft_display_name: str | None = None
    context_version: str
    semantic_fingerprint: tuple[object, ...]
    identity_fingerprint: tuple[object, ...]


def _normalized_aircraft_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def aircraft_display_name(aircraft_type: str) -> str:
    """Resolve a DCS type through the generic knowledge registry when possible."""
    needle = _normalized_aircraft_name(aircraft_type)
    for profile in aircraft_knowledge.list_profiles():
        candidates = {profile.aircraft_id, profile.display_name, *profile.aliases}
        if needle in {_normalized_aircraft_name(item) for item in candidates}:
            return profile.display_name
    return " ".join(aircraft_type.replace("_", " ").split())


class FlightContextService:
    """Freshness-aware facade over ORION's existing current telemetry store."""

    def __init__(
        self,
        telemetry: LiveTelemetryStore = live_telemetry,
        *,
        stale_after_seconds: float = 5.0,
    ) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("FlightContext stale threshold must be positive")
        self._telemetry = telemetry
        self._stale_after_seconds = stale_after_seconds

    def snapshot(self, *, now: datetime | None = None) -> FlightContextSnapshot:
        current = self._normalize_timestamp(now)
        raw = self._telemetry.snapshot()
        if raw.last_received_at is None:
            return FlightContextSnapshot(
                state=FlightContextState.NO_DCS,
                generation=raw.generation,
            )
        age = max(0.0, (current - raw.last_received_at).total_seconds())
        common = {
            "generation": raw.generation,
            "source": raw.source,
            "protocol_version": raw.protocol_version,
            "received_at": raw.last_received_at,
            "age_seconds": round(age, 3),
        }
        if age > self._stale_after_seconds:
            return FlightContextSnapshot(state=FlightContextState.STALE, **common)
        if raw.telemetry is None:
            return FlightContextSnapshot(
                state=FlightContextState.DCS_CONNECTED_NO_AIRCRAFT,
                **common,
            )
        state = raw.telemetry.state
        return FlightContextSnapshot(
            state=FlightContextState.FRESH,
            fresh=True,
            aircraft_type=state.aircraft_type,
            aircraft_display_name=aircraft_display_name(state.aircraft_type),
            latitude=state.position.latitude,
            longitude=state.position.longitude,
            altitude_m=state.position.altitude_m,
            altitude_agl_m=state.position.altitude_agl_m,
            heading_deg=state.heading_deg,
            true_airspeed_mps=state.true_airspeed_mps,
            vertical_speed_mps=state.vertical_speed_mps,
            **common,
        )

    def ai_update(self, base_instructions: str) -> AiFlightContextUpdate:
        snapshot = self.snapshot()
        semantic = self._semantic_fingerprint(snapshot)
        identity = (snapshot.state.value, snapshot.aircraft_type)
        return AiFlightContextUpdate(
            instructions=self._render_instructions(base_instructions, snapshot),
            state=snapshot.state,
            fresh=snapshot.fresh,
            generation=snapshot.generation,
            aircraft_type=snapshot.aircraft_type,
            aircraft_display_name=snapshot.aircraft_display_name,
            context_version=sha256(repr(semantic).encode("utf-8")).hexdigest()[:16],
            semantic_fingerprint=semantic,
            identity_fingerprint=identity,
        )

    @staticmethod
    def _normalize_timestamp(value: datetime | None) -> datetime:
        timestamp = value or datetime.now(UTC)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp

    @staticmethod
    def _semantic_fingerprint(snapshot: FlightContextSnapshot) -> tuple[object, ...]:
        if not snapshot.fresh:
            return (snapshot.state.value,)
        return (
            snapshot.state.value,
            snapshot.aircraft_type,
            round(snapshot.latitude or 0.0, 5),
            round(snapshot.longitude or 0.0, 5),
            round(snapshot.altitude_m or 0.0),
            None if snapshot.altitude_agl_m is None else round(snapshot.altitude_agl_m),
            round(snapshot.heading_deg or 0.0),
            round(snapshot.true_airspeed_mps or 0.0),
            round(snapshot.vertical_speed_mps or 0.0),
        )

    @staticmethod
    def _render_instructions(
        base_instructions: str,
        snapshot: FlightContextSnapshot,
    ) -> str:
        if not snapshot.fresh:
            reason = {
                FlightContextState.NO_DCS: "DCS telemetry has not been received",
                FlightContextState.DCS_CONNECTED_NO_AIRCRAFT: (
                    "DCS Export is connected but no player aircraft is available"
                ),
                FlightContextState.STALE: "the last DCS telemetry is stale",
            }[snapshot.state]
            context = (
                "Current DCS flight context is unavailable: "
                f"{reason}. Do not infer or invent the current aircraft, location, "
                "airfield, or flight state."
            )
            return compose_realtime_instructions(base_instructions, context)
        assert snapshot.altitude_m is not None
        assert snapshot.true_airspeed_mps is not None
        assert snapshot.vertical_speed_mps is not None
        assert snapshot.latitude is not None
        assert snapshot.longitude is not None
        altitude_ft = snapshot.altitude_m * 3.2808398950131
        tas_kt = snapshot.true_airspeed_mps * 1.9438444924406
        vertical_fpm = snapshot.vertical_speed_mps * 196.85039370079
        agl = "unavailable"
        if snapshot.altitude_agl_m is not None:
            agl_ft = snapshot.altitude_agl_m * 3.2808398950131
            agl = f"{agl_ft:.0f} ft ({snapshot.altitude_agl_m:.0f} m) AGL"
        position = FlightContextService._format_coordinates(
            snapshot.latitude,
            snapshot.longitude,
        )
        context = (
            "Current authoritative DCS flight context (fresh/live):\n"
            f"Aircraft: {snapshot.aircraft_display_name} "
            f"(DCS type {snapshot.aircraft_type}).\n"
            f"DCS heading: {snapshot.heading_deg:.0f} degrees in the range 000-359; "
            "the source does not establish that it is magnetic.\n"
            f"Altitude MSL: {altitude_ft:.0f} ft ({snapshot.altitude_m:.0f} m).\n"
            f"Height above ground: {agl}.\n"
            f"True airspeed: {tas_kt:.0f} kt ({snapshot.true_airspeed_mps:.1f} m/s), "
            "a non-negative speed magnitude. For an ordinary question about speed, "
            "answer with true airspeed, not vertical speed.\n"
            f"Signed vertical speed: {vertical_fpm:+.0f} ft/min "
            f"({snapshot.vertical_speed_mps:+.1f} m/s); positive means climbing, "
            "negative means descending, near zero means level.\n"
            f"Position: {position}. ORION has no deterministic current airfield name. "
            "Do not infer or guess a country or airfield from coordinates; state that "
            "the exact airfield is not deterministically known.\n"
            "Use only these values as current facts and do not invent unavailable fields."
        )
        return compose_realtime_instructions(base_instructions, context)

    @staticmethod
    def _format_coordinates(latitude: float, longitude: float) -> str:
        def component(value: float, positive: str, negative: str) -> str:
            hemisphere = positive if value >= 0 else negative
            absolute = abs(value)
            degrees = int(absolute)
            minutes = (absolute - degrees) * 60
            width = 2 if positive == "N" else 3
            return f"{degrees:0{width}d}° {minutes:05.2f}' {hemisphere}"

        return (
            f"{component(latitude, 'N', 'S')}, "
            f"{component(longitude, 'E', 'W')}"
        )


class FlightContextUpdateGate:
    """Per-AI-session coalescer for high-rate DCS telemetry."""

    def __init__(
        self,
        base_instructions: str,
        *,
        context: FlightContextService | None = None,
        minimum_update_interval_s: float = 5.0,
        refresh_interval_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if minimum_update_interval_s <= 0:
            raise ValueError("FlightContext minimum update interval must be positive")
        if refresh_interval_s < minimum_update_interval_s:
            raise ValueError("FlightContext refresh interval must not be shorter than minimum")
        self._base_instructions = base_instructions
        self._context = context or flight_context
        self._minimum_interval = minimum_update_interval_s
        self._refresh_interval = refresh_interval_s
        self._clock = clock
        self._last_update: AiFlightContextUpdate | None = None
        self._last_applied_at: float | None = None
        self._update_count = 0
        self._pending_update: AiFlightContextUpdate | None = None
        self._deferred_count = 0
        self._coalesced_count = 0
        self._lock = RLock()

    @property
    def update_count(self) -> int:
        with self._lock:
            return self._update_count

    @property
    def deferred_count(self) -> int:
        with self._lock:
            return self._deferred_count

    @property
    def coalesced_count(self) -> int:
        with self._lock:
            return self._coalesced_count

    def next_update(
        self,
        *,
        force: bool = False,
        safe_to_apply: bool = True,
    ) -> AiFlightContextUpdate | None:
        candidate = self._context.ai_update(self._base_instructions)
        now = self._clock()
        with self._lock:
            previous = self._last_update
            last_at = self._last_applied_at
            pending = self._pending_update
            if pending is not None:
                if (
                    candidate.semantic_fingerprint != pending.semantic_fingerprint
                    or candidate.identity_fingerprint != pending.identity_fingerprint
                ):
                    self._pending_update = candidate
                    self._coalesced_count += 1
                return self._pending_update if safe_to_apply else None
            if force or previous is None or last_at is None:
                eligible = True
            else:
                elapsed = max(0.0, now - last_at)
                if candidate.identity_fingerprint != previous.identity_fingerprint:
                    eligible = True
                elif candidate.semantic_fingerprint != previous.semantic_fingerprint:
                    eligible = elapsed >= self._minimum_interval
                else:
                    eligible = elapsed >= self._refresh_interval
            if not eligible:
                return None
            if not safe_to_apply:
                self._pending_update = candidate
                self._deferred_count += 1
                return None
            return candidate

    def mark_applied(self, update: AiFlightContextUpdate) -> int:
        with self._lock:
            self._last_update = update
            self._last_applied_at = self._clock()
            self._pending_update = None
            self._update_count += 1
            return self._update_count


flight_context = FlightContextService()
