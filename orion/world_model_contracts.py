"""Provider-neutral immutable contracts for the IA-2 World Model facade.

These models describe read results only.  They do not own simulator or mission
state and deliberately contain no provider, tool-calling, transport, or action
schema.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


WorldFactKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*$",
    ),
]
WorldUnit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
WorldGeneration = int | str


class WorldFactStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    RESTRICTED = "restricted"


class WorldFactAuthority(StrEnum):
    AUTHORITATIVE = "authoritative"
    OBSERVED = "observed"
    DERIVED = "derived"


class WorldFactSource(StrEnum):
    DCS_EXPORT = "dcs_export"
    MISSION_STORE = "mission_store"
    MISSION_BRIDGE = "mission_bridge"
    FA18C_COCKPIT = "fa18c_cockpit"
    WORLD_MODEL_GEOMETRY = "world_model_geometry"


class WorldFactReason(StrEnum):
    SOURCE_NOT_CONNECTED = "source_not_connected"
    SOURCE_STALE = "source_stale"
    NO_PLAYER_AIRCRAFT = "no_player_aircraft"
    VALUE_NOT_EXPORTED = "value_not_exported"
    INVALID_SOURCE_DATA = "invalid_source_data"
    AIRCRAFT_NOT_SUPPORTED = "aircraft_not_supported"
    AIRCRAFT_MAPPING_UNVALIDATED = "aircraft_mapping_unvalidated"
    UNIT_NOT_FOUND = "unit_not_found"
    MISSION_TRUTH_NOT_OBSERVATION = "mission_truth_not_observation"


class _WorldModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


FactValue = TypeVar("FactValue")


class WorldFact(_WorldModel, Generic[FactValue]):
    """One value plus deterministic provenance and freshness semantics."""

    key: WorldFactKey
    value: FactValue | None = None
    status: WorldFactStatus
    source: WorldFactSource
    authority: WorldFactAuthority
    observed_at: datetime | None = None
    age_seconds: float | None = Field(default=None, ge=0)
    generation: WorldGeneration | None = None
    unit: WorldUnit | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: WorldFactReason | None = None

    @field_validator("observed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("WorldFact.observed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_fact_shape(self) -> WorldFact[FactValue]:
        has_value = self.value is not None
        if self.status in {WorldFactStatus.KNOWN, WorldFactStatus.STALE} and not has_value:
            raise ValueError("known/stale WorldFact requires a value")
        if self.status in {
            WorldFactStatus.UNKNOWN,
            WorldFactStatus.UNAVAILABLE,
            WorldFactStatus.RESTRICTED,
        } and has_value:
            raise ValueError("unknown/unavailable/restricted WorldFact must not contain a value")
        if self.status is WorldFactStatus.KNOWN and self.reason is not None:
            raise ValueError("known WorldFact must not contain a failure reason")
        if self.status is not WorldFactStatus.KNOWN and self.reason is None:
            raise ValueError("non-known WorldFact requires a reason")
        if self.confidence is not None and self.authority is not WorldFactAuthority.OBSERVED:
            raise ValueError("confidence is only valid for uncertain observed facts")
        return self


class WorldPosition(_WorldModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float


class WorldAttitude(_WorldModel):
    pitch_deg: float | None = None
    bank_deg: float | None = None
    yaw_deg: float | None = None


class AircraftIdentity(_WorldModel):
    aircraft_type: str = Field(min_length=1, max_length=160)
    callsign: str | None = Field(default=None, max_length=120)


class AircraftSystemsState(_WorldModel):
    aircraft_id: str = Field(min_length=1, max_length=80)
    mapping_version: str = Field(min_length=1, max_length=160)
    tacan_enabled: bool | None = None
    tacan_channel: int | None = Field(default=None, ge=1, le=126)
    tacan_band: str | None = Field(default=None, pattern=r"^[XY]$")
    comm1_preset: int | None = Field(default=None, ge=1)
    comm1_frequency_mhz: float | None = Field(default=None, gt=0, lt=1000)
    comm2_preset: int | None = Field(default=None, ge=1)
    comm2_frequency_mhz: float | None = Field(default=None, gt=0, lt=1000)
    left_ddi_page: str | None = Field(default=None, max_length=80)
    right_ddi_page: str | None = Field(default=None, max_length=80)
    mpcd_page: str | None = Field(default=None, max_length=80)
    master_mode: str | None = Field(default=None, max_length=80)


class MissionIdentity(_WorldModel):
    mission_id: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=240)
    theatre: str | None = Field(default=None, max_length=160)
    mission_time_s: float = Field(ge=0)


class MissionBridgeIdentity(_WorldModel):
    session_id: str = Field(min_length=1, max_length=160)
    mission_name: str | None = Field(default=None, max_length=240)
    player_callsign: str | None = Field(default=None, max_length=120)
    sequence: int | None = Field(default=None, ge=0)


class MissionUnitVisibility(StrEnum):
    MISSION_TRUTH = "mission_truth"
    OBSERVED_CONTACT = "observed_contact"


class MissionUnitView(_WorldModel):
    unit_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=240)
    coalition: str = Field(min_length=1, max_length=40)
    category: str = Field(min_length=1, max_length=40)
    type_name: str | None = Field(default=None, max_length=160)
    position: WorldPosition
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    speed_mps: float | None = Field(default=None, ge=0)
    alive: bool
    visibility: MissionUnitVisibility


class MissionUnitSet(_WorldModel):
    units: tuple[MissionUnitView, ...] = ()
    total_matching: int = Field(ge=0)
    truncated: bool = False


class RangeBearingGeometry(_WorldModel):
    range_m: float = Field(ge=0)
    bearing_true_deg: float = Field(ge=0, lt=360)
    vertical_separation_m: float


class WorldQueryEnvelope(_WorldModel):
    schema_version: Literal["ia2.world.v1"] = "ia2.world.v1"
    query: str = Field(min_length=1, max_length=120)
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def require_aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("World query timestamps must be timezone-aware")
        return value


class OwnshipSnapshot(WorldQueryEnvelope):
    aircraft: WorldFact[AircraftIdentity]
    position: WorldFact[WorldPosition]
    heading_deg: WorldFact[float]
    attitude: WorldFact[WorldAttitude]
    true_airspeed_mps: WorldFact[float]
    ground_speed_mps: WorldFact[float]
    vertical_speed_mps: WorldFact[float]
    altitude_agl_m: WorldFact[float]
    fuel_fraction: WorldFact[float]


class OwnshipNavigationSnapshot(WorldQueryEnvelope):
    position: WorldFact[WorldPosition]
    heading_deg: WorldFact[float]
    altitude_agl_m: WorldFact[float]
    formatted_coordinates: WorldFact[str]
    terrain_elevation_m: WorldFact[float]
    nearest_airfield: WorldFact[str]
    route: WorldFact[tuple[str, ...]]


class AircraftSystemsSnapshot(WorldQueryEnvelope):
    systems: WorldFact[AircraftSystemsState]


class MissionIdentitySnapshot(WorldQueryEnvelope):
    mission: WorldFact[MissionIdentity]
    bridge: WorldFact[MissionBridgeIdentity]


class MissionUnitsQuery(_WorldModel):
    coalition: str | None = Field(default=None, min_length=1, max_length=40)
    alive_only: bool = True
    limit: int = Field(default=50, ge=1, le=200)


class MissionUnitsSnapshot(WorldQueryEnvelope):
    units: WorldFact[MissionUnitSet]


class ObservedContactsSnapshot(WorldQueryEnvelope):
    contacts: WorldFact[MissionUnitSet]


class GeometryToUnitQuery(_WorldModel):
    unit_id: str = Field(min_length=1, max_length=200)


class GeometryToUnitSnapshot(WorldQueryEnvelope):
    unit_id: str
    geometry: WorldFact[RangeBearingGeometry]
    closure_mps: WorldFact[float]
