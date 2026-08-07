from __future__ import annotations

from datetime import UTC, datetime
from math import atan2, cos, radians, sin, sqrt

from pydantic import BaseModel, Field

from orion.coalition_radio import CoalitionRadioUnit, coalition_radio
from orion.dcs_capabilities import DcsRecipientType
from orion.live_telemetry_store import live_telemetry
from orion.mission import Coalition, MissionSnapshot, MissionUnit
from orion.mission_store import mission_store


class OwnshipContext(BaseModel):
    aircraft_type: str
    latitude: float
    longitude: float
    altitude_m: float


class MissionContact(BaseModel):
    unit_id: str
    name: str
    coalition: Coalition
    type_name: str | None = None
    latitude: float
    longitude: float
    altitude_m: float
    distance_km: float | None = None
    bearing_deg: float | None = None


class SupportAsset(BaseModel):
    unit_id: str
    callsign: str
    role: DcsRecipientType
    unit_type: str | None = None
    frequency_mhz: float | None = None
    modulation: str | None = None
    available: bool = True


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
        )

    friendlies: list[MissionContact] = []
    hostiles: list[MissionContact] = []
    if snapshot is not None:
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
        awacs=_support_assets(radio_units, DcsRecipientType.AWACS),
        tankers=_support_assets(radio_units, DcsRecipientType.TANKER),
        jtac=_support_assets(radio_units, DcsRecipientType.JTAC),
        issues=issues,
    )


def _contact(unit: MissionUnit, ownship: OwnshipContext | None) -> MissionContact:
    distance_km = None
    bearing_deg = None
    if ownship is not None:
        distance_km, bearing_deg = _range_bearing(
            ownship.latitude, ownship.longitude, unit.position.latitude, unit.position.longitude
        )
    return MissionContact(
        unit_id=unit.unit_id,
        name=unit.name,
        coalition=unit.coalition,
        type_name=unit.type_name,
        latitude=unit.position.latitude,
        longitude=unit.position.longitude,
        altitude_m=unit.position.altitude_m,
        distance_km=distance_km,
        bearing_deg=bearing_deg,
    )


def _support_assets(units: list[CoalitionRadioUnit], role: DcsRecipientType) -> list[SupportAsset]:
    assets = [
        SupportAsset(
            unit_id=unit.unit_id,
            callsign=unit.callsign,
            role=role,
            unit_type=unit.unit_type,
            frequency_mhz=unit.frequency_mhz,
            modulation=unit.modulation.value if unit.modulation else None,
            available=unit.available,
        )
        for unit in units
        if unit.recipient_type is role
    ]
    return sorted(assets, key=lambda item: item.callsign)


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
