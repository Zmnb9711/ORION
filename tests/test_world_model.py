from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from orion.live_telemetry_store import LiveTelemetrySnapshot, LiveTelemetryStore
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_bridge_ingest import MissionBridgeState
from orion.models import AircraftState, Attitude, Position, TelemetryEnvelope, VelocityVector
from orion.world_model import WorldModelFacade
from orion.world_model_contracts import (
    GeometryToUnitQuery,
    MissionUnitVisibility,
    MissionUnitsQuery,
    WorldFact,
    WorldFactAuthority,
    WorldFactReason,
    WorldFactSource,
    WorldFactStatus,
)


NOW = datetime(2026, 8, 26, 16, 0, tzinfo=UTC)


@dataclass
class MissionOwner:
    snapshot: MissionSnapshot | None = None

    def get(self) -> MissionSnapshot | None:
        return self.snapshot


@dataclass
class BridgeOwner:
    snapshot: MissionBridgeState = field(default_factory=MissionBridgeState)

    def state(self) -> MissionBridgeState:
        return self.snapshot.model_copy(deep=True)


class BrokenOwner:
    def snapshot(self) -> object:
        return object()


def telemetry(*, age_seconds: float = 1, aircraft_type: str = "FA-18C_hornet", cockpit: dict[str, object] | None = None) -> LiveTelemetryStore:
    store = LiveTelemetryStore()
    store.set(
        TelemetryEnvelope(
            sequence=7,
            state=AircraftState(
                aircraft_type=aircraft_type,
                callsign="Colt 1-1",
                position=Position(latitude=0, longitude=0, altitude_m=1000, altitude_agl_m=700),
                heading_deg=90,
                true_airspeed_mps=200,
                vertical_speed_mps=-2,
                fuel_fraction=0.5,
                attitude=Attitude(pitch_deg=3, bank_deg=-4, yaw_deg=90),
                velocity_vector=VelocityVector(x_mps=3, y_mps=-2, z_mps=4),
                cockpit_state=cockpit,
            ),
        ),
        received_at=NOW - timedelta(seconds=age_seconds),
    )
    return store


def mission(*, age_seconds: float = 2, detected: bool = True) -> MissionSnapshot:
    return MissionSnapshot(
        mission_id="mission-1",
        name="IA-2 proof",
        theatre="Caucasus",
        mission_time_s=123,
        updated_at=NOW - timedelta(seconds=age_seconds),
        units=[
            MissionUnit(
                unit_id="red-1",
                name="Bandit",
                coalition=Coalition.RED,
                category=UnitCategory.AIRCRAFT,
                type_name="MiG-29",
                position=MissionPosition(latitude=0.1, longitude=0, altitude_m=1500),
                heading_deg=180,
                speed_mps=250,
                detected=detected,
            )
        ],
    )


def facade(
    *,
    telemetry_owner: object | None = None,
    mission_owner: object | None = None,
    bridge_owner: object | None = None,
) -> WorldModelFacade:
    return WorldModelFacade(
        telemetry=telemetry_owner if telemetry_owner is not None else telemetry(),  # type: ignore[arg-type]
        mission=mission_owner if mission_owner is not None else MissionOwner(mission()),  # type: ignore[arg-type]
        mission_bridge=bridge_owner if bridge_owner is not None else BridgeOwner(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


def test_fact_statuses_and_authority_rules() -> None:
    known = WorldFact[int](
        key="test.known",
        value=1,
        status=WorldFactStatus.KNOWN,
        source=WorldFactSource.DCS_EXPORT,
        authority=WorldFactAuthority.AUTHORITATIVE,
    )
    assert known.value == 1
    for status in (
        WorldFactStatus.UNKNOWN,
        WorldFactStatus.UNAVAILABLE,
        WorldFactStatus.RESTRICTED,
    ):
        fact = WorldFact[int](
            key=f"test.{status.value}",
            status=status,
            source=WorldFactSource.MISSION_STORE,
            authority=WorldFactAuthority.OBSERVED,
            reason=WorldFactReason.VALUE_NOT_EXPORTED,
        )
        assert fact.value is None
    stale = WorldFact[int](
        key="test.stale",
        value=1,
        status=WorldFactStatus.STALE,
        source=WorldFactSource.DCS_EXPORT,
        authority=WorldFactAuthority.AUTHORITATIVE,
        reason=WorldFactReason.SOURCE_STALE,
    )
    assert stale.status is WorldFactStatus.STALE


def test_invalid_fact_shapes_and_confidence_fail_closed() -> None:
    with pytest.raises(ValidationError):
        WorldFact[int](
            key="test.bad",
            status=WorldFactStatus.KNOWN,
            source=WorldFactSource.DCS_EXPORT,
            authority=WorldFactAuthority.AUTHORITATIVE,
        )
    with pytest.raises(ValidationError):
        WorldFact[int](
            key="test.bad",
            value=1,
            status=WorldFactStatus.RESTRICTED,
            source=WorldFactSource.DCS_EXPORT,
            authority=WorldFactAuthority.AUTHORITATIVE,
            reason=WorldFactReason.VALUE_NOT_EXPORTED,
        )
    with pytest.raises(ValidationError):
        WorldFact[int](
            key="test.bad",
            value=1,
            status=WorldFactStatus.KNOWN,
            source=WorldFactSource.DCS_EXPORT,
            authority=WorldFactAuthority.AUTHORITATIVE,
            confidence=0.8,
        )


def test_fresh_ownship_snapshot_has_provenance_generation_and_derived_speed() -> None:
    result = facade().ownship()
    assert result.aircraft.value is not None
    assert result.aircraft.value.callsign == "Colt 1-1"
    assert result.position.status is WorldFactStatus.KNOWN
    assert result.position.authority is WorldFactAuthority.AUTHORITATIVE
    assert result.position.age_seconds == 1
    assert result.position.generation == 1
    assert result.ground_speed_mps.value == 5
    assert result.ground_speed_mps.authority is WorldFactAuthority.DERIVED


def test_disconnected_heartbeat_and_stale_ownship_are_distinct() -> None:
    disconnected = facade(telemetry_owner=LiveTelemetryStore()).ownship()
    assert disconnected.position.status is WorldFactStatus.UNAVAILABLE
    assert disconnected.position.reason is WorldFactReason.SOURCE_NOT_CONNECTED

    heartbeat = LiveTelemetryStore()
    heartbeat.observe_heartbeat(received_at=NOW)
    no_aircraft = facade(telemetry_owner=heartbeat).ownship()
    assert no_aircraft.aircraft.reason is WorldFactReason.NO_PLAYER_AIRCRAFT

    stale = facade(telemetry_owner=telemetry(age_seconds=6)).ownship()
    assert stale.position.status is WorldFactStatus.STALE
    assert stale.position.reason is WorldFactReason.SOURCE_STALE


def test_navigation_exposes_deterministic_coordinates_and_explicit_gaps() -> None:
    result = facade().ownship_navigation()
    assert result.formatted_coordinates.status is WorldFactStatus.KNOWN
    assert result.formatted_coordinates.value == "00° 00.00' N, 000° 00.00' E"
    assert result.terrain_elevation_m.status is WorldFactStatus.UNAVAILABLE
    assert result.nearest_airfield.status is WorldFactStatus.UNAVAILABLE
    assert result.route.status is WorldFactStatus.UNAVAILABLE


def test_aircraft_systems_expose_only_validated_normalized_hornet_subset() -> None:
    cockpit: dict[str, object] = {
        "aircraft_id": "fa-18c",
        "mapping_version": "validated-v1",
        "mapping_validated": True,
        "tacan_enabled": True,
        "tacan_channel": 31,
        "tacan_band": "X",
        "comm1_frequency": 251.0,
        "left_ddi_page": "AZ/EL",
        "raw_arguments": {"secret_raw_arg": 0.5},
    }
    result = facade(telemetry_owner=telemetry(cockpit=cockpit)).aircraft_systems()
    assert result.systems.status is WorldFactStatus.KNOWN
    assert result.systems.authority is WorldFactAuthority.OBSERVED
    assert result.systems.value is not None
    assert result.systems.value.tacan_channel == 31
    assert "raw_arguments" not in result.systems.value.model_dump()


def test_missing_or_unsupported_aircraft_specific_data_is_unavailable() -> None:
    missing = facade().aircraft_systems().systems
    assert missing.reason is WorldFactReason.VALUE_NOT_EXPORTED
    unsupported = facade(telemetry_owner=telemetry(aircraft_type="F-16C_50")).aircraft_systems().systems
    assert unsupported.reason is WorldFactReason.AIRCRAFT_NOT_SUPPORTED
    unvalidated = facade(
        telemetry_owner=telemetry(cockpit={"aircraft_id": "fa-18c", "mapping_validated": False})
    ).aircraft_systems().systems
    assert unvalidated.reason is WorldFactReason.AIRCRAFT_MAPPING_UNVALIDATED


def test_mission_identity_separates_store_and_bridge_provenance() -> None:
    bridge = BridgeOwner(
        MissionBridgeState(
            connected=True,
            session_id="bridge-session",
            mission_name="Bridge mission",
            player_callsign="Colt 1-1",
            last_sequence=9,
            last_received_at=NOW - timedelta(seconds=1),
        )
    )
    result = facade(bridge_owner=bridge).mission_identity()
    assert result.mission.source is WorldFactSource.MISSION_STORE
    assert result.bridge.source is WorldFactSource.MISSION_BRIDGE
    assert result.bridge.value is not None
    assert result.bridge.value.sequence == 9


def test_disconnected_and_stale_mission_sources_are_explicit() -> None:
    disconnected = facade(mission_owner=MissionOwner()).mission_identity()
    assert disconnected.mission.status is WorldFactStatus.UNAVAILABLE
    stale = facade(mission_owner=MissionOwner(mission(age_seconds=31))).mission_units()
    assert stale.units.status is WorldFactStatus.STALE
    stale_bridge = BridgeOwner(
        MissionBridgeState(
            connected=False,
            stale=True,
            session_id="bridge-session",
            last_sequence=2,
            last_received_at=NOW - timedelta(seconds=20),
        )
    )
    assert facade(bridge_owner=stale_bridge).mission_identity().bridge.status is WorldFactStatus.STALE


def test_mission_truth_is_bounded_and_never_relabelled_as_observed() -> None:
    result = facade(mission_owner=MissionOwner(mission(detected=False))).mission_units(
        MissionUnitsQuery(coalition="red", limit=1)
    )
    assert result.units.value is not None
    assert result.units.value.units[0].visibility is MissionUnitVisibility.MISSION_TRUTH
    assert "detected" not in result.units.value.units[0].model_dump()
    observed = facade().observed_contacts().contacts
    assert observed.status is WorldFactStatus.RESTRICTED
    assert observed.reason is WorldFactReason.MISSION_TRUTH_NOT_OBSERVATION


def test_geometry_is_core_derived_and_closure_remains_unavailable() -> None:
    result = facade().geometry_to_unit(GeometryToUnitQuery(unit_id="red-1"))
    assert result.geometry.status is WorldFactStatus.KNOWN
    assert result.geometry.authority is WorldFactAuthority.DERIVED
    assert result.geometry.value is not None
    assert result.geometry.value.range_m == pytest.approx(11119.508, abs=0.01)
    assert result.geometry.value.bearing_true_deg == 0
    assert result.geometry.value.vertical_separation_m == 500
    assert result.closure_mps.status is WorldFactStatus.UNAVAILABLE


def test_missing_unit_is_unknown() -> None:
    result = facade().geometry_to_unit(GeometryToUnitQuery(unit_id="missing"))
    assert result.geometry.status is WorldFactStatus.UNKNOWN
    assert result.geometry.reason is WorldFactReason.UNIT_NOT_FOUND


def test_invalid_source_data_fails_closed() -> None:
    result = facade(telemetry_owner=BrokenOwner()).ownship()
    assert result.position.status is WorldFactStatus.UNAVAILABLE
    assert result.position.reason is WorldFactReason.INVALID_SOURCE_DATA


def test_queries_do_not_mutate_authoritative_state() -> None:
    owner = MissionOwner(mission())
    before = owner.snapshot.model_dump_json() if owner.snapshot is not None else ""
    model = facade(mission_owner=owner)
    model.mission_units()
    model.geometry_to_unit(GeometryToUnitQuery(unit_id="red-1"))
    assert owner.snapshot is not None
    assert owner.snapshot.model_dump_json() == before


def test_contracts_are_immutable_and_serialization_is_stable() -> None:
    result = facade().ownship()
    first = result.model_dump_json()
    second = facade().ownship().model_dump_json()
    assert first == second
    with pytest.raises(ValidationError):
        result.query = "changed"  # type: ignore[misc]


def test_world_model_modules_have_no_provider_transport_or_tool_imports() -> None:
    root = Path(__file__).parents[1] / "orion"
    forbidden = ("yandex", "qwen", "openai", "srs", "realtime_tools")
    for filename in ("world_model.py", "world_model_contracts.py"):
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ] + [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(token in imported.casefold() for imported in imports for token in forbidden)
