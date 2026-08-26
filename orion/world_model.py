"""IA-2 read-only World Model Query Facade over authoritative Core stores."""

from __future__ import annotations

from datetime import UTC, datetime
from math import atan2, cos, degrees, hypot, radians, sin, sqrt
from typing import Callable, Protocol, TypedDict

from orion.fa18c_cockpit_adapter import normalize_hornet_cockpit_state
from orion.live_telemetry_store import LiveTelemetrySnapshot, live_telemetry
from orion.mission import MissionSnapshot
from orion.mission_bridge_ingest import MissionBridgeState, mission_bridge_telemetry
from orion.mission_store import mission_store
from orion.world_model_contracts import (
    AircraftIdentity,
    AircraftSystemsSnapshot,
    AircraftSystemsState,
    GeometryToUnitQuery,
    GeometryToUnitSnapshot,
    MissionBridgeIdentity,
    MissionIdentity,
    MissionIdentitySnapshot,
    MissionUnitSet,
    MissionUnitView,
    MissionUnitVisibility,
    MissionUnitsQuery,
    MissionUnitsSnapshot,
    ObservedContactsSnapshot,
    OwnshipNavigationSnapshot,
    OwnshipSnapshot,
    RangeBearingGeometry,
    WorldAttitude,
    WorldFact,
    WorldFactAuthority,
    WorldFactReason,
    WorldFactSource,
    WorldFactStatus,
    WorldPosition,
)


class TelemetryStateOwner(Protocol):
    def snapshot(self) -> LiveTelemetrySnapshot: ...


class MissionStateOwner(Protocol):
    def get(self) -> MissionSnapshot | None: ...


class MissionBridgeStateOwner(Protocol):
    def state(self) -> MissionBridgeState: ...


class _FactMetadata(TypedDict):
    observed_at: datetime | None
    age_seconds: float | None
    generation: int | str | None


class WorldModelFacade:
    """Cheap read projection; never stores, mutates, transmits, or acts on facts."""

    def __init__(
        self,
        *,
        telemetry: TelemetryStateOwner = live_telemetry,
        mission: MissionStateOwner = mission_store,
        mission_bridge: MissionBridgeStateOwner = mission_bridge_telemetry,
        ownship_stale_after_seconds: float = 5.0,
        mission_stale_after_seconds: float = 30.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if ownship_stale_after_seconds <= 0 or mission_stale_after_seconds <= 0:
            raise ValueError("World Model stale thresholds must be positive")
        self._telemetry = telemetry
        self._mission = mission
        self._mission_bridge = mission_bridge
        self._ownship_stale_after = ownship_stale_after_seconds
        self._mission_stale_after = mission_stale_after_seconds
        self._clock = clock

    def ownship(self) -> OwnshipSnapshot:
        now = self._now()
        raw, error = self._telemetry_snapshot()
        if error is not None or raw is None:
            return self._empty_ownship(now, error or WorldFactReason.INVALID_SOURCE_DATA)
        if raw.last_received_at is None:
            return self._empty_ownship(now, WorldFactReason.SOURCE_NOT_CONNECTED, raw.generation)
        age = self._age(now, raw.last_received_at)
        if raw.telemetry is None:
            return self._empty_ownship(
                now,
                WorldFactReason.NO_PLAYER_AIRCRAFT,
                raw.generation,
                raw.last_received_at,
                age,
            )
        state = raw.telemetry.state
        freshness = self._freshness(age, self._ownship_stale_after)
        common = self._metadata(raw.last_received_at, age, raw.generation)
        missing_status = WorldFactStatus.UNKNOWN
        identity = AircraftIdentity(aircraft_type=state.aircraft_type, callsign=state.callsign)
        position = WorldPosition(
            latitude=state.position.latitude,
            longitude=state.position.longitude,
            altitude_m=state.position.altitude_m,
        )
        attitude = None
        if state.attitude is not None and any(
            item is not None
            for item in (state.attitude.pitch_deg, state.attitude.bank_deg, state.attitude.yaw_deg)
        ):
            attitude = WorldAttitude(**state.attitude.model_dump())
        vector = state.velocity_vector
        ground_speed = None
        if vector is not None and vector.x_mps is not None and vector.z_mps is not None:
            ground_speed = hypot(vector.x_mps, vector.z_mps)
        return OwnshipSnapshot(
            query="ownship.current_state",
            generated_at=now,
            aircraft=self._value_fact("ownship.aircraft", identity, freshness, **common),
            position=self._value_fact("ownship.position", position, freshness, **common),
            heading_deg=self._value_fact(
                "ownship.heading_deg", state.heading_deg, freshness, unit="deg", **common
            ),
            attitude=(
                self._value_fact("ownship.attitude", attitude, freshness, **common)
                if attitude is not None
                else self._missing_fact(
                    "ownship.attitude", missing_status, WorldFactReason.VALUE_NOT_EXPORTED, **common
                )
            ),
            true_airspeed_mps=self._value_fact(
                "ownship.true_airspeed_mps",
                state.true_airspeed_mps,
                freshness,
                unit="m/s",
                **common,
            ),
            ground_speed_mps=(
                self._value_fact(
                    "ownship.ground_speed_mps",
                    ground_speed,
                    freshness,
                    source=WorldFactSource.WORLD_MODEL_GEOMETRY,
                    authority=WorldFactAuthority.DERIVED,
                    unit="m/s",
                    **common,
                )
                if ground_speed is not None
                else self._missing_fact(
                    "ownship.ground_speed_mps",
                    missing_status,
                    WorldFactReason.VALUE_NOT_EXPORTED,
                    source=WorldFactSource.WORLD_MODEL_GEOMETRY,
                    authority=WorldFactAuthority.DERIVED,
                    **common,
                )
            ),
            vertical_speed_mps=self._value_fact(
                "ownship.vertical_speed_mps",
                state.vertical_speed_mps,
                freshness,
                unit="m/s",
                **common,
            ),
            altitude_agl_m=(
                self._value_fact(
                    "ownship.altitude_agl_m",
                    state.position.altitude_agl_m,
                    freshness,
                    unit="m",
                    **common,
                )
                if state.position.altitude_agl_m is not None
                else self._missing_fact(
                    "ownship.altitude_agl_m",
                    missing_status,
                    WorldFactReason.VALUE_NOT_EXPORTED,
                    unit="m",
                    **common,
                )
            ),
            fuel_fraction=(
                self._value_fact(
                    "ownship.fuel_fraction", state.fuel_fraction, freshness, unit="ratio", **common
                )
                if state.fuel_fraction is not None
                else self._missing_fact(
                    "ownship.fuel_fraction",
                    missing_status,
                    WorldFactReason.VALUE_NOT_EXPORTED,
                    unit="ratio",
                    **common,
                )
            ),
        )

    def ownship_navigation(self) -> OwnshipNavigationSnapshot:
        snapshot = self.ownship()
        now = snapshot.generated_at
        position = snapshot.position
        coordinates: WorldFact[str]
        if position.value is None:
            coordinates = self._missing_fact(
                "ownship.navigation.formatted_coordinates",
                position.status,
                position.reason or WorldFactReason.INVALID_SOURCE_DATA,
                source=WorldFactSource.WORLD_MODEL_GEOMETRY,
                authority=WorldFactAuthority.DERIVED,
                observed_at=position.observed_at,
                age_seconds=position.age_seconds,
                generation=position.generation,
            )
        else:
            coordinates = self._value_fact(
                "ownship.navigation.formatted_coordinates",
                self._format_coordinates(position.value.latitude, position.value.longitude),
                position.status,
                source=WorldFactSource.WORLD_MODEL_GEOMETRY,
                authority=WorldFactAuthority.DERIVED,
                observed_at=position.observed_at,
                age_seconds=position.age_seconds,
                generation=position.generation,
            )
        return OwnshipNavigationSnapshot(
            query="ownship.navigation_summary",
            generated_at=now,
            position=position,
            heading_deg=snapshot.heading_deg,
            altitude_agl_m=snapshot.altitude_agl_m,
            formatted_coordinates=coordinates,
            terrain_elevation_m=self._missing_fact(
                "ownship.navigation.terrain_elevation_m",
                WorldFactStatus.UNAVAILABLE,
                WorldFactReason.VALUE_NOT_EXPORTED,
                source=WorldFactSource.DCS_EXPORT,
                authority=WorldFactAuthority.AUTHORITATIVE,
                observed_at=position.observed_at,
                age_seconds=position.age_seconds,
                generation=position.generation,
                unit="m",
            ),
            nearest_airfield=self._missing_fact(
                "ownship.navigation.nearest_airfield",
                WorldFactStatus.UNAVAILABLE,
                WorldFactReason.VALUE_NOT_EXPORTED,
                source=WorldFactSource.DCS_EXPORT,
                authority=WorldFactAuthority.AUTHORITATIVE,
                observed_at=position.observed_at,
                age_seconds=position.age_seconds,
                generation=position.generation,
            ),
            route=self._missing_fact(
                "ownship.navigation.route",
                WorldFactStatus.UNAVAILABLE,
                WorldFactReason.VALUE_NOT_EXPORTED,
                source=WorldFactSource.DCS_EXPORT,
                authority=WorldFactAuthority.AUTHORITATIVE,
                observed_at=position.observed_at,
                age_seconds=position.age_seconds,
                generation=position.generation,
            ),
        )

    def aircraft_systems(self) -> AircraftSystemsSnapshot:
        now = self._now()
        raw, error = self._telemetry_snapshot()
        if error is not None or raw is None:
            return self._systems_missing(now, error or WorldFactReason.INVALID_SOURCE_DATA)
        common = self._metadata(raw.last_received_at, self._optional_age(now, raw.last_received_at), raw.generation)
        if raw.last_received_at is None:
            return self._systems_missing(now, WorldFactReason.SOURCE_NOT_CONNECTED, **common)
        if raw.telemetry is None:
            return self._systems_missing(now, WorldFactReason.NO_PLAYER_AIRCRAFT, **common)
        state = raw.telemetry.state
        if self._normalized_aircraft(state.aircraft_type) not in {"fa18chornet", "fa18c"}:
            return self._systems_missing(now, WorldFactReason.AIRCRAFT_NOT_SUPPORTED, **common)
        cockpit = normalize_hornet_cockpit_state(state.cockpit_state)
        if cockpit is None:
            return self._systems_missing(now, WorldFactReason.VALUE_NOT_EXPORTED, **common)
        if not cockpit.mapping_validated or not cockpit.mapping_version:
            return self._systems_missing(now, WorldFactReason.AIRCRAFT_MAPPING_UNVALIDATED, **common)
        age = common["age_seconds"]
        assert isinstance(age, float)
        freshness = self._freshness(age, self._ownship_stale_after)
        systems = AircraftSystemsState(
            aircraft_id=cockpit.aircraft_id,
            mapping_version=cockpit.mapping_version,
            tacan_enabled=cockpit.tacan_enabled,
            tacan_channel=cockpit.tacan_channel,
            tacan_band=cockpit.tacan_band,
            comm1_preset=cockpit.comm1_preset,
            comm1_frequency_mhz=cockpit.comm1_frequency,
            comm2_preset=cockpit.comm2_preset,
            comm2_frequency_mhz=cockpit.comm2_frequency,
            left_ddi_page=cockpit.left_ddi_page,
            right_ddi_page=cockpit.right_ddi_page,
            mpcd_page=cockpit.mpcd_page,
            master_mode=cockpit.master_mode,
        )
        return AircraftSystemsSnapshot(
            query="ownship.aircraft_systems",
            generated_at=now,
            systems=self._value_fact(
                "ownship.aircraft_systems",
                systems,
                freshness,
                source=WorldFactSource.FA18C_COCKPIT,
                authority=WorldFactAuthority.OBSERVED,
                **common,
            ),
        )

    def mission_identity(self) -> MissionIdentitySnapshot:
        now = self._now()
        mission, mission_error = self._mission_snapshot()
        if mission_error is not None or mission is None:
            mission_fact = self._missing_fact(
                "mission.identity",
                WorldFactStatus.UNAVAILABLE,
                mission_error or WorldFactReason.SOURCE_NOT_CONNECTED,
                source=WorldFactSource.MISSION_STORE,
                authority=WorldFactAuthority.AUTHORITATIVE,
            )
        else:
            age = self._age(now, mission.updated_at)
            mission_fact = self._value_fact(
                "mission.identity",
                MissionIdentity(
                    mission_id=mission.mission_id,
                    name=mission.name,
                    theatre=mission.theatre,
                    mission_time_s=mission.mission_time_s,
                ),
                self._freshness(age, self._mission_stale_after),
                source=WorldFactSource.MISSION_STORE,
                authority=WorldFactAuthority.AUTHORITATIVE,
                observed_at=mission.updated_at,
                age_seconds=age,
                generation=self._mission_generation(mission),
            )
        bridge_fact = self._bridge_fact(now)
        return MissionIdentitySnapshot(
            query="mission.identity_state",
            generated_at=now,
            mission=mission_fact,
            bridge=bridge_fact,
        )

    def mission_units(self, query: MissionUnitsQuery | None = None) -> MissionUnitsSnapshot:
        selected = query or MissionUnitsQuery()
        now = self._now()
        mission, error = self._mission_snapshot()
        if error is not None or mission is None:
            return MissionUnitsSnapshot(
                query="mission.units.mission_truth",
                generated_at=now,
                units=self._missing_fact(
                    "mission.units",
                    WorldFactStatus.UNAVAILABLE,
                    error or WorldFactReason.SOURCE_NOT_CONNECTED,
                    source=WorldFactSource.MISSION_STORE,
                    authority=WorldFactAuthority.AUTHORITATIVE,
                ),
            )
        matching = [
            unit
            for unit in mission.units
            if (selected.coalition is None or unit.coalition.value == selected.coalition.casefold())
            and (not selected.alive_only or unit.alive)
        ]
        matching.sort(key=lambda item: (item.coalition.value, item.name, item.unit_id))
        views = tuple(
            MissionUnitView(
                unit_id=unit.unit_id,
                name=unit.name,
                coalition=unit.coalition.value,
                category=unit.category.value,
                type_name=unit.type_name,
                position=WorldPosition(
                    latitude=unit.position.latitude,
                    longitude=unit.position.longitude,
                    altitude_m=unit.position.altitude_m,
                ),
                heading_deg=unit.heading_deg,
                speed_mps=unit.speed_mps,
                alive=unit.alive,
                visibility=MissionUnitVisibility.MISSION_TRUTH,
            )
            for unit in matching[: selected.limit]
        )
        age = self._age(now, mission.updated_at)
        value = MissionUnitSet(
            units=views,
            total_matching=len(matching),
            truncated=len(matching) > selected.limit,
        )
        return MissionUnitsSnapshot(
            query="mission.units.mission_truth",
            generated_at=now,
            units=self._value_fact(
                "mission.units",
                value,
                self._freshness(age, self._mission_stale_after),
                source=WorldFactSource.MISSION_STORE,
                authority=WorldFactAuthority.AUTHORITATIVE,
                observed_at=mission.updated_at,
                age_seconds=age,
                generation=self._mission_generation(mission),
            ),
        )

    def observed_contacts(self) -> ObservedContactsSnapshot:
        """Refuse to project omniscient MissionStore units as detected contacts."""

        return ObservedContactsSnapshot(
            query="mission.contacts.observed",
            generated_at=self._now(),
            contacts=self._missing_fact(
                "mission.contacts.observed",
                WorldFactStatus.RESTRICTED,
                WorldFactReason.MISSION_TRUTH_NOT_OBSERVATION,
                source=WorldFactSource.MISSION_STORE,
                authority=WorldFactAuthority.OBSERVED,
            ),
        )

    def geometry_to_unit(self, query: GeometryToUnitQuery) -> GeometryToUnitSnapshot:
        now = self._now()
        telemetry, telemetry_error = self._telemetry_snapshot()
        mission, mission_error = self._mission_snapshot()
        missing_reason = telemetry_error or mission_error
        if telemetry is None or mission is None or missing_reason is not None:
            return self._geometry_missing(now, query.unit_id, missing_reason or WorldFactReason.SOURCE_NOT_CONNECTED)
        if telemetry.last_received_at is None:
            return self._geometry_missing(now, query.unit_id, WorldFactReason.SOURCE_NOT_CONNECTED)
        if telemetry.telemetry is None:
            return self._geometry_missing(now, query.unit_id, WorldFactReason.NO_PLAYER_AIRCRAFT)
        unit = next((item for item in mission.units if item.unit_id == query.unit_id), None)
        if unit is None:
            return self._geometry_missing(now, query.unit_id, WorldFactReason.UNIT_NOT_FOUND, unknown=True)
        own = telemetry.telemetry.state.position
        geometry = self._range_bearing(
            own.latitude,
            own.longitude,
            own.altitude_m,
            unit.position.latitude,
            unit.position.longitude,
            unit.position.altitude_m,
        )
        telemetry_age = self._age(now, telemetry.last_received_at)
        mission_age = self._age(now, mission.updated_at)
        stale = telemetry_age > self._ownship_stale_after or mission_age > self._mission_stale_after
        status = WorldFactStatus.STALE if stale else WorldFactStatus.KNOWN
        observed_at = min(telemetry.last_received_at, mission.updated_at)
        age = max(telemetry_age, mission_age)
        generation = f"{telemetry.generation}:{self._mission_generation(mission)}"
        return GeometryToUnitSnapshot(
            query="geometry.ownship_to_mission_unit",
            generated_at=now,
            unit_id=query.unit_id,
            geometry=self._value_fact(
                "geometry.ownship_to_unit",
                geometry,
                status,
                source=WorldFactSource.WORLD_MODEL_GEOMETRY,
                authority=WorldFactAuthority.DERIVED,
                observed_at=observed_at,
                age_seconds=age,
                generation=generation,
            ),
            closure_mps=self._missing_fact(
                "geometry.closure_mps",
                WorldFactStatus.UNAVAILABLE,
                WorldFactReason.VALUE_NOT_EXPORTED,
                source=WorldFactSource.WORLD_MODEL_GEOMETRY,
                authority=WorldFactAuthority.DERIVED,
                observed_at=observed_at,
                age_seconds=age,
                generation=generation,
                unit="m/s",
            ),
        )

    def _empty_ownship(
        self,
        now: datetime,
        reason: WorldFactReason,
        generation: int | str | None = None,
        observed_at: datetime | None = None,
        age_seconds: float | None = None,
    ) -> OwnshipSnapshot:
        common = self._metadata(observed_at, age_seconds, generation)
        def missing(key: str, unit: str | None = None) -> WorldFact:  # type: ignore[type-arg]
            return self._missing_fact(
                key,
                WorldFactStatus.UNAVAILABLE,
                reason,
                unit=unit,
                **common,
            )
        return OwnshipSnapshot(
            query="ownship.current_state",
            generated_at=now,
            aircraft=missing("ownship.aircraft"),
            position=missing("ownship.position"),
            heading_deg=missing("ownship.heading_deg", "deg"),
            attitude=missing("ownship.attitude"),
            true_airspeed_mps=missing("ownship.true_airspeed_mps", "m/s"),
            ground_speed_mps=self._missing_fact(
                "ownship.ground_speed_mps",
                WorldFactStatus.UNAVAILABLE,
                reason,
                source=WorldFactSource.WORLD_MODEL_GEOMETRY,
                authority=WorldFactAuthority.DERIVED,
                unit="m/s",
                **common,
            ),
            vertical_speed_mps=missing("ownship.vertical_speed_mps", "m/s"),
            altitude_agl_m=missing("ownship.altitude_agl_m", "m"),
            fuel_fraction=missing("ownship.fuel_fraction", "ratio"),
        )

    def _systems_missing(
        self,
        now: datetime,
        reason: WorldFactReason,
        observed_at: datetime | None = None,
        age_seconds: float | None = None,
        generation: int | str | None = None,
    ) -> AircraftSystemsSnapshot:
        return AircraftSystemsSnapshot(
            query="ownship.aircraft_systems",
            generated_at=now,
            systems=self._missing_fact(
                "ownship.aircraft_systems",
                WorldFactStatus.UNAVAILABLE,
                reason,
                source=WorldFactSource.FA18C_COCKPIT,
                authority=WorldFactAuthority.OBSERVED,
                observed_at=observed_at,
                age_seconds=age_seconds,
                generation=generation,
            ),
        )

    def _bridge_fact(self, now: datetime) -> WorldFact[MissionBridgeIdentity]:
        try:
            state = self._mission_bridge.state()
        except Exception:
            return self._missing_fact(
                "mission.bridge",
                WorldFactStatus.UNAVAILABLE,
                WorldFactReason.INVALID_SOURCE_DATA,
                source=WorldFactSource.MISSION_BRIDGE,
                authority=WorldFactAuthority.AUTHORITATIVE,
            )
        if state.last_received_at is None or state.session_id is None:
            return self._missing_fact(
                "mission.bridge",
                WorldFactStatus.UNAVAILABLE,
                WorldFactReason.SOURCE_NOT_CONNECTED,
                source=WorldFactSource.MISSION_BRIDGE,
                authority=WorldFactAuthority.AUTHORITATIVE,
                generation=state.last_sequence,
            )
        try:
            age = self._age(now, state.last_received_at)
        except ValueError:
            return self._missing_fact(
                "mission.bridge",
                WorldFactStatus.UNAVAILABLE,
                WorldFactReason.INVALID_SOURCE_DATA,
                source=WorldFactSource.MISSION_BRIDGE,
                authority=WorldFactAuthority.AUTHORITATIVE,
                generation=state.last_sequence,
            )
        status = WorldFactStatus.STALE if state.stale or not state.connected else WorldFactStatus.KNOWN
        return self._value_fact(
            "mission.bridge",
            MissionBridgeIdentity(
                session_id=state.session_id,
                mission_name=state.mission_name,
                player_callsign=state.player_callsign,
                sequence=state.last_sequence,
            ),
            status,
            source=WorldFactSource.MISSION_BRIDGE,
            authority=WorldFactAuthority.AUTHORITATIVE,
            observed_at=state.last_received_at,
            age_seconds=age,
            generation=state.last_sequence,
        )

    def _geometry_missing(
        self,
        now: datetime,
        unit_id: str,
        reason: WorldFactReason,
        *,
        unknown: bool = False,
    ) -> GeometryToUnitSnapshot:
        status = WorldFactStatus.UNKNOWN if unknown else WorldFactStatus.UNAVAILABLE
        common = {
            "source": WorldFactSource.WORLD_MODEL_GEOMETRY,
            "authority": WorldFactAuthority.DERIVED,
        }
        return GeometryToUnitSnapshot(
            query="geometry.ownship_to_mission_unit",
            generated_at=now,
            unit_id=unit_id,
            geometry=self._missing_fact("geometry.ownship_to_unit", status, reason, **common),
            closure_mps=self._missing_fact(
                "geometry.closure_mps", status, reason, unit="m/s", **common
            ),
        )

    def _telemetry_snapshot(
        self,
    ) -> tuple[LiveTelemetrySnapshot | None, WorldFactReason | None]:
        try:
            raw = self._telemetry.snapshot()
            if raw.last_received_at is not None:
                self._require_aware(raw.last_received_at)
            return raw, None
        except (AttributeError, TypeError, ValueError):
            return None, WorldFactReason.INVALID_SOURCE_DATA

    def _mission_snapshot(self) -> tuple[MissionSnapshot | None, WorldFactReason | None]:
        try:
            snapshot = self._mission.get()
            if snapshot is not None:
                self._require_aware(snapshot.updated_at)
                snapshot = snapshot.model_copy(deep=True)
            return snapshot, None
        except (AttributeError, TypeError, ValueError):
            return None, WorldFactReason.INVALID_SOURCE_DATA

    @staticmethod
    def _value_fact(
        key: str,
        value: object,
        status: WorldFactStatus,
        *,
        source: WorldFactSource = WorldFactSource.DCS_EXPORT,
        authority: WorldFactAuthority = WorldFactAuthority.AUTHORITATIVE,
        observed_at: datetime | None = None,
        age_seconds: float | None = None,
        generation: int | str | None = None,
        unit: str | None = None,
    ) -> WorldFact:  # type: ignore[type-arg]
        return WorldFact(
            key=key,
            value=value,
            status=status,
            source=source,
            authority=authority,
            observed_at=observed_at,
            age_seconds=age_seconds,
            generation=generation,
            unit=unit,
            reason=WorldFactReason.SOURCE_STALE if status is WorldFactStatus.STALE else None,
        )

    @staticmethod
    def _missing_fact(
        key: str,
        status: WorldFactStatus,
        reason: WorldFactReason,
        *,
        source: WorldFactSource = WorldFactSource.DCS_EXPORT,
        authority: WorldFactAuthority = WorldFactAuthority.AUTHORITATIVE,
        observed_at: datetime | None = None,
        age_seconds: float | None = None,
        generation: int | str | None = None,
        unit: str | None = None,
    ) -> WorldFact:  # type: ignore[type-arg]
        return WorldFact(
            key=key,
            status=status,
            source=source,
            authority=authority,
            observed_at=observed_at,
            age_seconds=age_seconds,
            generation=generation,
            unit=unit,
            reason=reason,
        )

    @staticmethod
    def _metadata(
        observed_at: datetime | None,
        age_seconds: float | None,
        generation: int | str | None,
    ) -> _FactMetadata:
        return {
            "observed_at": observed_at,
            "age_seconds": age_seconds,
            "generation": generation,
        }

    def _now(self) -> datetime:
        value = self._clock()
        self._require_aware(value)
        return value

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("World Model source timestamps must be timezone-aware")

    @classmethod
    def _age(cls, now: datetime, observed_at: datetime) -> float:
        cls._require_aware(observed_at)
        return round(max(0.0, (now - observed_at).total_seconds()), 3)

    @classmethod
    def _optional_age(cls, now: datetime, observed_at: datetime | None) -> float | None:
        return None if observed_at is None else cls._age(now, observed_at)

    @staticmethod
    def _freshness(age: float, threshold: float) -> WorldFactStatus:
        return WorldFactStatus.STALE if age > threshold else WorldFactStatus.KNOWN

    @staticmethod
    def _mission_generation(mission: MissionSnapshot) -> str:
        return f"{mission.mission_id}:{mission.updated_at.isoformat()}"

    @staticmethod
    def _normalized_aircraft(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    @staticmethod
    def _format_coordinates(latitude: float, longitude: float) -> str:
        def component(value: float, positive: str, negative: str, width: int) -> str:
            hemisphere = positive if value >= 0 else negative
            absolute = abs(value)
            whole = int(absolute)
            minutes = (absolute - whole) * 60
            return f"{whole:0{width}d}\u00b0 {minutes:05.2f}' {hemisphere}"

        return (
            f"{component(latitude, 'N', 'S', 2)}, "
            f"{component(longitude, 'E', 'W', 3)}"
        )

    @staticmethod
    def _range_bearing(
        latitude_a: float,
        longitude_a: float,
        altitude_a_m: float,
        latitude_b: float,
        longitude_b: float,
        altitude_b_m: float,
    ) -> RangeBearingGeometry:
        earth_radius_m = 6_371_008.8
        phi_a, phi_b = radians(latitude_a), radians(latitude_b)
        dphi = radians(latitude_b - latitude_a)
        dlambda = radians(longitude_b - longitude_a)
        haversine = sin(dphi / 2) ** 2 + cos(phi_a) * cos(phi_b) * sin(dlambda / 2) ** 2
        horizontal = 2 * earth_radius_m * atan2(
            sqrt(haversine), sqrt(max(0.0, 1 - haversine))
        )
        y = sin(dlambda) * cos(phi_b)
        x = cos(phi_a) * sin(phi_b) - sin(phi_a) * cos(phi_b) * cos(dlambda)
        bearing = (degrees(atan2(y, x)) + 360) % 360
        return RangeBearingGeometry(
            range_m=round(horizontal, 3),
            bearing_true_deg=round(bearing, 3),
            vertical_separation_m=round(altitude_b_m - altitude_a_m, 3),
        )


world_model = WorldModelFacade()
