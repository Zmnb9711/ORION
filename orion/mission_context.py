from __future__ import annotations

from datetime import UTC, datetime
from math import atan2, cos, radians, sin, sqrt

from pydantic import BaseModel, Field

from orion.coalition_radio import CoalitionRadioUnit, coalition_radio
from orion.dcs_capabilities import DcsRecipientType
from orion.live_telemetry_store import live_telemetry
from orion.mission import Coalition, MissionUnit
from orion.mission_store import mission_store


class OwnshipContext(BaseModel):
    aircraft_type: str
    latitude: float
    longitude: float
    altitude_m: float
    heading_deg: float | None = None
    true_airspeed_mps: float | None = None


class MissionContact(BaseModel):
    unit_id: str
    name: str
    coalition: Coalition
    type_name: str | None = None
    latitude: float
    longitude: float
    altitude_m: float
    speed_mps: float | None = None
    distance_km: float | None = None
    bearing_deg: float | None = None


class SupportAsset(BaseModel):
    unit_id: str
    callsign: str
    role: DcsRecipientType
    coalition: Coalition = Coalition.UNKNOWN
    unit_type: str | None = None
    frequency_mhz: float | None = None
    modulation: str | None = None
    tacan_channel: int | None = None
    tacan_band: str | None = None
    aar_available: bool | None = None
    available: bool = True
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    heading_deg: float | None = None
    speed_mps: float | None = None
    distance_km: float | None = None
    bearing_deg: float | None = None
    position_source: str | None = None


class LiveMissionContext(BaseModel):
    available: bool
    mission_id: str | None = None
    mission_name: str | None = None
    theatre: str | None = None
    mission_time_s: float | None = None
    ownship: OwnshipContext | None = None
    friendlies: list[MissionContact] = Field(default_factory=list)
    hostiles: list[MissionContact] = Field(default_factory=list)
    awacs: list[SupportAsset] = Field(default_factory=list)
    tankers: list[SupportAsset] = Field(default_factory=list)
    jtac: list[SupportAsset] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    issues: list[str] = Field(default_factory=list)


def build_live_mission_context() -> LiveMissionContext:
    snapshot = mission_store.get()
    telemetry = live_telemetry.get()
    issues: list[str] = []
    if snapshot is None:
        issues.append("mission_snapshot_unavailable")
    if telemetry is None:
        issues.append("ownship_telemetry_unavailable")

    ownship = None
    if telemetry is not None:
        position = telemetry.state.position
        ownship = OwnshipContext(
            aircraft_type=telemetry.state.aircraft_type,
            latitude=position.latitude,
            longitude=position.longitude,
            altitude_m=position.altitude_m,
            heading_deg=telemetry.state.heading_deg,
            true_airspeed_mps=telemetry.state.true_airspeed_mps,
        )

    friendlies: list[MissionContact] = []
    hostiles: list[MissionContact] = []
    mission_units: dict[str, MissionUnit] = {}
    if snapshot is not None:
        mission_units = {unit.unit_id: unit for unit in snapshot.units}
        for unit in snapshot.units:
            if not unit.alive or not unit.detected:
                continue
            contact = _contact(unit, ownship)
            if unit.coalition is Coalition.BLUE:
                friendlies.append(contact)
            elif unit.coalition is Coalition.RED:
                hostiles.append(contact)

    friendlies.sort(key=_contact_sort_key)
    hostiles.sort(key=_contact_sort_key)
    radio_units = coalition_radio.list()
    return LiveMissionContext(
        available=snapshot is not None,
        mission_id=snapshot.mission_id if snapshot else None,
        mission_name=snapshot.name if snapshot else None,
        theatre=snapshot.theatre if snapshot else None,
        mission_time_s=snapshot.mission_time_s if snapshot else None,
        ownship=ownship,
        friendlies=friendlies,
        hostiles=hostiles,
        awacs=_support_assets(radio_units, DcsRecipientType.AWACS, mission_units, ownship),
        tankers=_support_assets(radio_units, DcsRecipientType.TANKER, mission_units, ownship),
        jtac=_support_assets(radio_units, DcsRecipientType.JTAC, mission_units, ownship),
        issues=issues,
    )


def _contact(unit: MissionUnit, ownship: OwnshipContext | None) -> MissionContact:
    distance_km = None
    bearing_deg = None
    if ownship is not None:
        distance_km, bearing_deg = _range_bearing(ownship.latitude, ownship.longitude, unit.position.latitude, unit.position.longitude)
    return MissionContact(
        unit_id=unit.unit_id,
        name=unit.name,
        coalition=unit.coalition,
        type_name=unit.type_name,
        latitude=unit.position.latitude,
        longitude=unit.position.longitude,
        altitude_m=unit.position.altitude_m,
        speed_mps=unit.speed_mps,
        distance_km=distance_km,
        bearing_deg=bearing_deg,
    )


def _support_assets(
    units: list[CoalitionRadioUnit],
    role: DcsRecipientType,
    mission_units: dict[str, MissionUnit],
    ownship: OwnshipContext | None,
) -> list[SupportAsset]:
    assets: list[SupportAsset] = []
    for unit in units:
        if unit.recipient_type is not role:
            continue
        mission_unit = mission_units.get(unit.unit_id)
        latitude = longitude = altitude_m = heading_deg = speed_mps = distance_km = bearing_deg = None
        position_source = None
        coalition = _coalition(unit.coalition)
        if mission_unit is not None and mission_unit.alive and mission_unit.detected:
            latitude = mission_unit.position.latitude
            longitude = mission_unit.position.longitude
            altitude_m = mission_unit.position.altitude_m
            heading_deg = mission_unit.heading_deg
            speed_mps = mission_unit.speed_mps
            coalition = mission_unit.coalition
            position_source = "mission_snapshot"
            if ownship is not None:
                distance_km, bearing_deg = _range_bearing(ownship.latitude, ownship.longitude, latitude, longitude)
        assets.append(
            SupportAsset(
                unit_id=unit.unit_id,
                callsign=unit.callsign,
                role=role,
                coalition=coalition,
                unit_type=unit.unit_type,
                frequency_mhz=unit.frequency_mhz,
                modulation=unit.modulation.value if unit.modulation else None,
                tacan_channel=unit.tacan_channel,
                tacan_band=unit.tacan_band,
                aar_available=unit.aar_available,
                available=unit.available,
                latitude=latitude,
                longitude=longitude,
                altitude_m=altitude_m,
                heading_deg=heading_deg,
                speed_mps=speed_mps,
                distance_km=distance_km,
                bearing_deg=bearing_deg,
                position_source=position_source,
            )
        )
    return sorted(assets, key=lambda item: (item.distance_km if item.distance_km is not None else float("inf"), item.callsign))


def _coalition(value: str) -> Coalition:
    try:
        return Coalition(value.casefold())
    except ValueError:
        return Coalition.UNKNOWN


def _contact_sort_key(contact: MissionContact) -> tuple[float, str]:
    return (contact.distance_km if contact.distance_km is not None else float("inf"), contact.name)


def _range_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    earth_radius_km = 6371.0088
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    distance = 2 * earth_radius_km * atan2(sqrt(a), sqrt(max(0.0, 1 - a)))
    y = sin(dlambda) * cos(phi2)
    x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dlambda)
    bearing = (atan2(y, x) * 180 / 3.141592653589793 + 360) % 360
    return round(distance, 1), round(bearing, 1)
