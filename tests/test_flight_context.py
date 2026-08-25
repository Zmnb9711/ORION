from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from orion.flight_context import (
    FlightContextService,
    FlightContextState,
    FlightContextUpdateGate,
)
from orion.realtime_ai_instructions import (
    FLIGHT_CONTEXT_END,
    FLIGHT_CONTEXT_START,
    ORION_REALTIME_BASE_INSTRUCTIONS,
)
from orion.live_telemetry_store import LiveTelemetryStore
from orion.models import AircraftState, Position, TelemetryEnvelope


def _telemetry(
    aircraft_type: str = "FA-18C_hornet",
    *,
    sequence: int = 1,
    latitude: float = 41.61021,
    heading: float = 251.4,
) -> TelemetryEnvelope:
    return TelemetryEnvelope(
        protocol_version="0.3",
        source="dcs-export",
        sequence=sequence,
        model_time_s=120.5,
        state=AircraftState(
            aircraft_type=aircraft_type,
            position=Position(
                latitude=latitude,
                longitude=41.59991,
                altitude_m=37.4,
                altitude_agl_m=1.2,
            ),
            heading_deg=heading,
            true_airspeed_mps=0.7,
            vertical_speed_mps=-0.1,
        ),
    )


def test_no_dcs_context_is_explicit_and_does_not_invent_aircraft() -> None:
    context = FlightContextService(LiveTelemetryStore())
    snapshot = context.snapshot()
    update = context.ai_update("Base instructions")
    assert snapshot.state is FlightContextState.NO_DCS
    assert not snapshot.fresh
    assert snapshot.aircraft_type is None
    assert "unavailable" in update.instructions
    assert "Do not infer or invent" in update.instructions
    assert "Hornet" not in update.instructions


def test_fresh_field_representative_telemetry_propagates_all_stage6a_fields() -> None:
    store = LiveTelemetryStore()
    received = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    store.set(_telemetry(), received_at=received)
    context = FlightContextService(store)
    snapshot = context.snapshot(now=received + timedelta(seconds=1))
    assert snapshot.state is FlightContextState.FRESH
    assert snapshot.fresh
    assert snapshot.aircraft_type == "FA-18C_hornet"
    assert snapshot.aircraft_display_name == "F/A-18C Hornet"
    assert snapshot.latitude == 41.61021
    assert snapshot.longitude == 41.59991
    assert snapshot.altitude_m == 37.4
    assert snapshot.altitude_agl_m == 1.2
    assert snapshot.heading_deg == 251.4
    assert snapshot.true_airspeed_mps == 0.7
    assert snapshot.vertical_speed_mps == -0.1


def test_ai_presentation_has_verified_aviation_units_and_signed_vertical_rate() -> None:
    store = LiveTelemetryStore()
    store.set(_telemetry())
    instructions = FlightContextService(store).ai_update(
        ORION_REALTIME_BASE_INSTRUCTIONS
    ).instructions
    assert "F/A-18C Hornet" in instructions
    assert "DCS heading: 251 degrees" in instructions
    assert "does not establish that it is magnetic" in instructions
    assert "Altitude MSL: 123 ft (37 m)" in instructions
    assert "4 ft (1 m) AGL" in instructions
    assert "True airspeed: 1 kt (0.7 m/s)" in instructions
    assert "Signed vertical speed: -20 ft/min (-0.1 m/s)" in instructions
    assert "negative means descending" in instructions
    assert "41° 36.61' N, 041° 35.99' E" in instructions
    assert "Do not infer or guess a country or airfield" in instructions


def test_canonical_identity_and_single_context_block_survive_many_updates() -> None:
    store = LiveTelemetryStore()
    context = FlightContextService(store)
    instructions = ORION_REALTIME_BASE_INSTRUCTIONS
    for sequence in range(1, 51):
        store.set(_telemetry(sequence=sequence, latitude=41.61 + sequence / 100_000))
        instructions = context.ai_update(instructions).instructions
        assert "Your name is ORION" in instructions
        assert instructions.count(FLIGHT_CONTEXT_START) == 1
        assert instructions.count(FLIGHT_CONTEXT_END) == 1


def test_aircraft_change_replaces_current_authoritative_context() -> None:
    store = LiveTelemetryStore()
    context = FlightContextService(store)
    store.set(_telemetry())
    first = context.ai_update("Base")
    store.set(_telemetry("F-16C_50", sequence=2))
    second = context.ai_update("Base")
    assert first.aircraft_type == "FA-18C_hornet"
    assert second.aircraft_type == "F-16C_50"
    assert first.identity_fingerprint != second.identity_fingerprint
    assert "F-16C 50" in second.instructions


def test_stale_telemetry_is_never_rendered_as_current() -> None:
    store = LiveTelemetryStore()
    received = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    store.set(_telemetry(), received_at=received)
    context = FlightContextService(store, stale_after_seconds=5.0)
    snapshot = context.snapshot(now=received + timedelta(seconds=5.001))
    assert snapshot.state is FlightContextState.STALE
    assert not snapshot.fresh
    assert snapshot.aircraft_type is None


def test_export_heartbeat_after_player_loss_immediately_invalidates_aircraft() -> None:
    store = LiveTelemetryStore()
    store.set(_telemetry())
    store.observe_heartbeat(source="dcs-export", protocol_version="0.3")
    snapshot = FlightContextService(store).snapshot()
    assert snapshot.state is FlightContextState.DCS_CONNECTED_NO_AIRCRAFT
    assert snapshot.aircraft_type is None
    assert snapshot.source == "dcs-export"


def test_rapid_telemetry_is_coalesced_to_a_bounded_provider_update_rate() -> None:
    store = LiveTelemetryStore()
    context = FlightContextService(store)
    clock_value = [100.0]
    gate = FlightContextUpdateGate(
        "Base",
        context=context,
        clock=lambda: clock_value[0],
    )
    store.set(_telemetry())
    initial = gate.next_update(force=True)
    assert initial is not None
    gate.mark_applied(initial)
    for sequence in range(2, 1002):
        store.set(
            _telemetry(sequence=sequence, latitude=41.61021 + sequence / 1_000_000),
        )
        assert gate.next_update() is None
    clock_value[0] += 5.0
    coalesced = gate.next_update()
    assert coalesced is not None
    gate.mark_applied(coalesced)
    assert gate.update_count == 2


def test_identity_change_bypasses_kinematic_coalescing_delay() -> None:
    store = LiveTelemetryStore()
    context = FlightContextService(store)
    gate = FlightContextUpdateGate("Base", context=context, clock=lambda: 100.0)
    store.set(_telemetry())
    first = gate.next_update(force=True)
    assert first is not None
    gate.mark_applied(first)
    store.set(_telemetry("F-16C_50", sequence=2))
    assert gate.next_update() is not None


def test_active_turn_defers_and_latest_context_coalesces_until_safe_boundary() -> None:
    store = LiveTelemetryStore()
    context = FlightContextService(store)
    clock_value = [100.0]
    gate = FlightContextUpdateGate(
        ORION_REALTIME_BASE_INSTRUCTIONS,
        context=context,
        clock=lambda: clock_value[0],
    )
    store.set(_telemetry())
    initial = gate.next_update(force=True)
    assert initial is not None
    gate.mark_applied(initial)

    store.set(_telemetry("F-16C_50", sequence=2, heading=90))
    assert gate.next_update(safe_to_apply=False) is None
    assert gate.deferred_count == 1
    store.set(_telemetry("A-10C_2", sequence=3, heading=180))
    assert gate.next_update(safe_to_apply=False) is None
    assert gate.coalesced_count == 1

    latest = gate.next_update(safe_to_apply=True)
    assert latest is not None
    assert latest.aircraft_type == "A-10C_2"
    assert "DCS heading: 180 degrees" in latest.instructions
    gate.mark_applied(latest)
    assert gate.update_count == 2


def test_flight_context_is_current_only_and_does_not_write_history(
    monkeypatch,
) -> None:  # noqa: ANN001
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("disk write")))
    store = LiveTelemetryStore()
    for sequence in range(1, 101):
        store.set(_telemetry(sequence=sequence))
    raw = store.snapshot()
    assert raw.telemetry is not None
    assert raw.telemetry.sequence == 100
    assert raw.generation == 100


def test_flight_context_models_and_repr_cannot_contain_session_secrets() -> None:
    secret = "stage6-secret-must-not-leak"
    store = LiveTelemetryStore()
    store.set(_telemetry())
    context = FlightContextService(store)
    rendered = repr(context.snapshot()) + repr(context.ai_update("Base"))
    assert secret not in rendered
    assert "api_key" not in rendered
    assert "eam_password" not in rendered
