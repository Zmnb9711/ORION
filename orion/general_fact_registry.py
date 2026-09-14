"""Core fact policy, never an input vocabulary or a store of simulator values."""
from __future__ import annotations

from enum import StrEnum
import hashlib
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Exposure(StrEnum):
    # Primary status is independent of source/authority/module properties.
    EXPOSED_AUTHORITATIVE = "FOUNDATION_EXPOSED"
    EXPOSED_DERIVED = "FOUNDATION_EXPOSED"
    KNOWN_BUT_NOT_EXPOSED = "AVAILABLE_BUT_NOT_CONNECTED"
    RAW_ONLY = "SEMANTICS_UNCERTAIN"
    SEMANTICS_UNCERTAIN = "SEMANTICS_UNCERTAIN"
    SOURCE_UNRELIABLE = "SEMANTICS_UNCERTAIN"
    RESTRICTED = "RESTRICTED"
    UNAVAILABLE = "UNAVAILABLE"


class FactDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    meaning: str
    namespace: Literal["ownship", "aircraft", "mission"] = "ownship"
    value_type: Literal["identity", "position", "number", "raw"] = "number"
    unit: str | None = None
    source: str = "dcs_export"
    authority: str = "authoritative"
    freshness_seconds: int = Field(default=5, gt=0, le=30)
    generation_semantics: str = "One Core live-telemetry generation and receive timestamp."
    tool: str | None = "orion.world.ownship.get"
    version: str = "1.0"
    permission: str = "world.ownship.read"
    snapshot_field: str | None = None
    world_key: str | None = None
    source_unit: str | None = None
    leaves: tuple[str, ...] = ()
    raw_field: str
    normalized_field: str
    exposure: Exposure
    reason: str
    applicability: tuple[str, ...] = ()  # Empty = common contract, not universal availability.
    presentation: Literal["identity", "position", "heading", "altitude", "pitch", "bank", "yaw", "agl", "tas", "vertical_speed"] | None = None
    minimum: float | None = None
    maximum: float | None = None

    @property
    def exposed(self) -> bool:
        return self.exposure in {Exposure.EXPOSED_AUTHORITATIVE, Exposure.EXPOSED_DERIVED}


def _fact(identity, meaning, field, key, raw, leaves, presentation, *, unit=None,
          value_type: Literal["identity", "position", "number", "raw"] = "number", source_unit=None, minimum=None, maximum=None):
    return FactDefinition(capability=identity, meaning=meaning, snapshot_field=field, world_key=key,
        raw_field=raw, normalized_field="state.aircraft_type" if field == "aircraft" else
            "state.position.altitude_agl_m" if field == "altitude_agl_m" else "state."+field,
        leaves=tuple(leaves), presentation=presentation,
        unit=unit, source_unit=source_unit, value_type=value_type, minimum=minimum, maximum=maximum,
        namespace="aircraft" if identity.startswith("aircraft.") else "ownship",
        exposure=Exposure.EXPOSED_AUTHORITATIVE,
        reason="Typed WorldModel selection via existing ownship ToolGateway; availability/freshness checked per read.")


# Ordering is Core presentation policy. Metadata contains no user utterances.
_SAFE = (
    _fact("aircraft.identity", "Current player aircraft type, not general aircraft knowledge.",
          "aircraft", "ownship.aircraft", "LoGetSelfData.Name", ("ownship.aircraft.aircraft_type",),
          "identity", value_type="identity"),
    _fact("ownship.position", "Current player latitude and longitude only, not a place name or altitude.",
          "position", "ownship.position", "LoGetSelfData.LatLongAlt.Lat/Long",
          ("ownship.position.latitude", "ownship.position.longitude"), "position", value_type="position", unit="deg"),
    _fact("ownship.heading", "Current player heading in Core degrees, not track, route or proven magnetic bearing.",
          "heading_deg", "ownship.heading_deg", "LoGetSelfData.Heading plus explicit heading_valid quality bit",
          ("ownship.heading_deg",), "heading", unit="deg", source_unit="deg", minimum=0, maximum=360),
    _fact("ownship.altitude_msl", "Current geometric altitude above sea level, metres; not barometric or radar altitude.",
          "position", "ownship.position", "LoGetSelfData.LatLongAlt.Alt",
          ("ownship.position.altitude_m",), "altitude", unit="m", value_type="position"),
    _fact("ownship.pitch", "Current ADI pitch angle, degrees; positive nose-up, not climb rate.",
          "attitude", "ownship.attitude", "LoGetADIPitchBankYaw first return, radians converted to degrees",
          ("ownship.attitude.pitch_deg",), "pitch", unit="deg", minimum=-90, maximum=90),
    _fact("ownship.bank", "Current signed ADI bank angle, degrees; not heading or turn rate.",
          "attitude", "ownship.attitude", "LoGetADIPitchBankYaw second return, radians converted to degrees",
          ("ownship.attitude.bank_deg",), "bank", unit="deg", minimum=-180, maximum=180),
    _fact("ownship.yaw", "Current ADI yaw angle normalized to 0..360 degrees; no magnetic/track equivalence asserted.",
          "attitude", "ownship.attitude", "LoGetADIPitchBankYaw third return, degrees modulo360",
          ("ownship.attitude.yaw_deg",), "yaw", unit="deg", minimum=0, maximum=360),
    _fact("ownship.true_airspeed", "Current true airspeed in metres per second; not indicated or ground speed.",
          "true_airspeed_mps", "ownship.true_airspeed_mps", "LoGetTrueAirSpeed with source_quality.true_airspeed=true",
          ("ownship.true_airspeed_mps",), "tas", unit="m/s", source_unit="m/s", minimum=0),
    _fact("ownship.vertical_speed", "Current signed vertical speed in metres per second; positive climb, negative descent.",
          "vertical_speed_mps", "ownship.vertical_speed_mps", "LoGetVerticalVelocity with source_quality.vertical_speed=true",
          ("ownship.vertical_speed_mps",), "vertical_speed", unit="m/s", source_unit="m/s"),
    _fact("ownship.altitude_agl", "Current geometric height above local ground in metres, not radar or barometric altitude.",
          "altitude_agl_m", "ownship.altitude_agl_m", "LoGetAltitudeAboveGroundLevel with source_quality.altitude_agl=true (no clamp)",
          ("ownship.altitude_agl_m",), "agl", unit="m", source_unit="m", minimum=0),
)


def _blocked(identity, status, raw, normalized, reason, *, source="dcs_export", authority="authoritative"):
    return FactDefinition(capability=identity, meaning=identity, raw_field=raw, normalized_field=normalized,
        value_type="raw", tool=None, permission="", source=source, authority=authority,
        namespace="mission" if identity.startswith("mission.") else "aircraft" if identity.startswith("aircraft.") else "ownship",
        freshness_seconds=10 if source == "mission_bridge" else 30 if source == "mission_store" else 5,
        applicability=("FA-18C_hornet",) if source == "fa18c_cockpit" else (),
        generation_semantics="Combined ownship (5s) and mission (30s) inputs; no single telemetry generation." if identity == "mission.range_bearing"
                             else "Separate mission/Bridge generation and receive time." if source in {"mission_store", "mission_bridge"}
                             else "One Core live-telemetry generation and receive timestamp.",
        exposure=status, reason=reason)


_BLOCKED = (
    _blocked("ownship.fuel_fraction", Exposure.SEMANTICS_UNCERTAIN, "LoGetEngineInfo fuel_internal/external",
        "state.fuel versus state.fuel_fraction", "Exporter sends module_dependent internal_raw/external_raw, not fraction. No trustworthy normalization/denominator or per-module validation."),
    _blocked("ownship.ground_speed", Exposure.SOURCE_UNRELIABLE, "LoGetVectorVelocity x/z",
        "WorldModel.ground_speed_mps", "Derived hypot(x,z) is correct, but exporter substitutes zero for missing vector components without quality flags.",
        source="world_model_geometry", authority="derived"),
    _blocked("aircraft.callsign", Exposure.UNAVAILABLE, "not in exporter packet", "state.callsign",
        "Model accepts callsign, current generic exporter does not populate it; do not substitute Bridge/SRS identity."),
    _blocked("ownship.radio", Exposure.RAW_ONLY, "capabilities.radios=not_yet_mapped", "state.radios",
        "No generic radio fields emitted; cockpit presets are not SRS transport/frequency state."),
    _blocked("ownship.cockpit", Exposure.KNOWN_BUT_NOT_EXPOSED, "hornetCockpitState raw_arguments",
        "WorldModel.aircraft_systems", "Observed/module-specific; active calibrated mapping/profile and exact field applicability require separate per-leaf verification.",
        source="fa18c_cockpit", authority="observed"),
    _blocked("ownship.contacts", Exposure.RESTRICTED, "LoGetTWSInfo / sighting gated by sensor export permission",
        "state.ew/sensors", "Raw sensor data has no trusted observed-contact owner. Mission truth must not substitute for observation.", authority="observed"),
    _blocked("mission.world", Exposure.KNOWN_BUT_NOT_EXPOSED, "Mission Store / Bridge",
        "WorldModel mission queries", "Separate source/permissions/temporal basis; not an ownship snapshot and not observed AWACS knowledge.", source="mission_store"),
    _blocked("ownship.place", Exposure.UNAVAILABLE, "no geospatial owner", "none", "Coordinates do not provide country/city/region."),
    _blocked("mission.day_night", Exposure.UNAVAILABLE, "no combined date/time/solar projection", "none",
        "Wall clock is not mission civil/solar time.", source="mission_store"),
)

_LEAF_AUDIT = (
    *(_blocked("ownship.airframe."+part+"."+leaf, Exposure.RAW_ONLY, "LoGetMechInfo."+part+"."+leaf,
        "state.airframe."+part+"."+leaf,
        "Raw module-dependent status/value; no universal boolean/enum/range or typed WorldModel read binding.")
      for part in ("gear", "flaps", "speedbrakes", "hook", "wing", "canopy", "refueling", "wheelbrakes") for leaf in ("status", "value")),
    *(_blocked("ownship.propulsion."+part+"."+side, Exposure.SEMANTICS_UNCERTAIN,
        "LoGetEngineInfo."+part+"."+side, "state.propulsion."+part+"."+side,
        "Raw engine side retained. Units/scales/module completeness and missing-engine semantics not normalized; no typed read binding.")
      for part in ("rpm", "temperature", "fuel_consumption", "hydraulic_pressure") for side in ("left", "right")),
    *(_blocked("ownship.fuel."+part, Exposure.SEMANTICS_UNCERTAIN, "LoGetEngineInfo.fuel_"+part.replace("_raw", ""),
        "state.fuel."+part, "Exporter labels documented_unit=kg but explicitly module_dependent; fraction versus mass is not validated per module.")
      for part in ("internal_raw", "external_raw")),
    *(_blocked("ownship.navigation."+leaf, Exposure.RAW_ONLY, "LoGetNavigationInfo/LoGetRadioBeaconsStatus",
        "state.navigation."+leaf, "Raw navigation mode/requirements/beacon value; no normalized typed fact or universal current/commanded-state semantics.")
      for leaf in ("system_mode.master", "system_mode.submode", "acs_mode", "requirements.roll", "requirements.pitch", "requirements.speed",
                   "beacons.airfield_near", "beacons.airfield_far", "beacons.course_lock", "beacons.glideslope_lock")),
    *(_blocked("ownship.payload."+leaf, Exposure.RAW_ONLY, "LoGetPayloadInfo/LoGetSnares",
        "state.payload."+leaf, "Raw stores projection; station/type identity, missing versus zero and module completeness need typed WorldModel mapping before admission.")
      for leaf in ("current_station", "cannon_shells", "stations.station", "stations.container", "stations.weapon_type", "stations.count",
                   "countermeasures.chaff", "countermeasures.flare")),
    *(_blocked("ownship.ew."+leaf, Exposure.RESTRICTED, "LoGetTWSInfo", "state.ew."+leaf,
        "Sensor-export permission applies; raw emitter set is not an admitted observed-contact model.", authority="observed")
      for leaf in ("mode", "emitters.id", "emitters.type", "emitters.power", "emitters.azimuth_rad", "emitters.priority", "emitters.signal_type")),
    *(_blocked("ownship.sensors."+leaf, Exposure.RESTRICTED, "LoGetSightingSystemInfo", "state.sensors."+leaf,
        "Raw sensor field/permission, no validated Core selector for module-specific semantics.", authority="observed")
      for leaf in ("manufacturer", "launch_authorized", "radar_on", "optical_system_on", "ecm_on", "laser_on", "prf.current", "prf.selection")),
    *(_blocked("ownship.cockpit.raw."+leaf, Exposure.RAW_ONLY, "hornetCockpitState GetDevice(0) argument mapping",
        "state.cockpit_state.raw_arguments."+leaf, "F/A-18C calibrated raw argument; not generic radio/airframe state and never an AI-selectable argument ID.",
        source="fa18c_cockpit", authority="observed")
      for leaf in ("comm1_selector", "comm2_selector", "tacan_power", "tacan_channel_tens", "tacan_channel_ones", "tacan_xy",
                   "left_ddi_brightness", "right_ddi_brightness", "mpcd_brightness")),
    *(_blocked("ownship.cockpit."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED, "HornetCockpitState decoder / optional injected fields",
        "WorldModel.aircraft_systems."+leaf,
        "Existing OBSERVED facade is gated by mapping_validated/version. This audit has no per-leaf active calibration/applicability receipt; do not import raw or mission/requested settings as observed state.",
        source="fa18c_cockpit", authority="observed")
      for leaf in ("tacan_enabled", "tacan_channel", "tacan_band", "comm1_preset", "comm1_frequency_mhz", "comm2_preset", "comm2_frequency_mhz",
                   "left_ddi_page", "right_ddi_page", "mpcd_page", "master_mode")),
    *(_blocked("ownship."+leaf, Exposure.UNAVAILABLE, "not emitted by current generic exporter", "no trusted normalized source",
        "No current exported and typed read binding; no inference from other measurements.")
      for leaf in ("indicated_airspeed", "mach", "barometric_altitude", "radar_altitude", "ground_track", "magnetic_heading", "throttle",
                   "afterburner", "engine_running", "engine_count", "lights", "warnings", "damage", "airborne")),
    *(_blocked("mission."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED, "MissionSnapshot / MissionBridge state", "WorldModel mission projection",
        "Separate mission identity/truth or derived geometry, not ownship observed state. Requires its own scoped selector, permissions and temporal/presentation validation.",
        source="mission_bridge" if leaf.startswith("bridge.") else "world_model_geometry" if leaf == "range_bearing" else "mission_store",
        authority="derived" if leaf == "range_bearing" else "authoritative")
      for leaf in ("identity", "name", "theatre", "time", "units", "units.position", "units.alive", "units.detected", "units.coalition",
                   "units.category", "units.type", "units.heading", "units.speed", "range_bearing", "bridge.session", "bridge.name",
                   "bridge.player_callsign", "bridge.units", "bridge.landmarks", "bridge.presets")),
    _blocked("ownship.velocity_vector", Exposure.SOURCE_UNRELIABLE, "LoGetVectorVelocity", "state.velocity_vector",
        "x/y/z may be manufactured zero; not a reliable raw source for further derived facts."),
    _blocked("ownship.telemetry_metadata", Exposure.KNOWN_BUT_NOT_EXPOSED, "Export sequence/model_time/source/diagnostics/capabilities/heading_valid",
        "TelemetryEnvelope and Core receive metadata", "Quality/transport metadata, not user flight-state facts; diagnostics are opt-in argument changes, not speech."),
)

_METADATA_AUDIT = (
    *(_blocked("ownship.source_quality."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "Direct API return validated BEFORE fallback/clamp", "state.source_quality."+leaf,
        "Internal source admission metadata, not a selectable flight measurement.")
      for leaf in ("true_airspeed", "vertical_speed", "altitude_agl")),
    *(_blocked("ownship.envelope."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "TelemetryEnvelope / LiveTelemetryStore", leaf,
        "Transport, clock or owner metadata; used for provenance, not spoken flight facts.")
      for leaf in ("protocol_version", "source", "sequence", "captured_at", "model_time_s",
                   "state.timestamp", "last_received_at", "generation", "state.heading_valid")),
    *(_blocked("ownship.capabilities."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "Export.lua tableStatus/eitherTableStatus", "state.capabilities."+leaf,
        "Domain/table presence, NOT per-leaf validity or authorization; never a flight-state value.")
      for leaf in ("identity", "kinematics", "airframe", "propulsion", "fuel", "navigation", "radios",
                   "payload", "ew", "sensors", "cockpit", "mission_world")),
    *(_blocked("ownship.velocity_vector."+leaf, Exposure.SOURCE_UNRELIABLE,
        "LoGetVectorVelocity component or synthesized zero", "state.velocity_vector."+leaf,
        "First unsafe boundary: Export replaces missing component with zero without source quality.")
      for leaf in ("x_mps", "y_mps", "z_mps")),
    *(_blocked("ownship.cockpit.metadata."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "HornetCockpitState / calibrated profile", "state.cockpit_state."+leaf,
        "Mapping identity/quality, not physical state; WorldModel currently calls decoder without an ID mapping.",
        source="fa18c_cockpit", authority="observed")
      for leaf in ("aircraft_id", "mapping_version", "mapping_validated")),
    *(_blocked("ownship.cockpit."+leaf, Exposure.RESTRICTED,
        "Optional HornetCockpitState mission/requested inputs", "HornetCockpitState."+leaf,
        "Desired/mission-assigned value is not measured cockpit state; not exported by current packet.",
        source="fa18c_cockpit", authority="observed")
      for leaf in ("mission_tacan_channel", "mission_tacan_band", "requested_tacan_channel", "requested_tacan_band",
                   "mission_comm1_preset", "mission_comm1_frequency", "requested_comm1_preset", "requested_comm1_frequency",
                   "mission_comm2_preset", "mission_comm2_frequency", "requested_comm2_preset", "requested_comm2_frequency")),
    _blocked("ownship.cockpit.sensor_of_interest", Exposure.UNAVAILABLE, "HornetCockpitState optional injected field",
        "HornetCockpitState.sensor_of_interest", "Not emitted by Export or selected by current WorldModel facade.",
        source="fa18c_cockpit", authority="observed"),
    *(_blocked("ownship.navigation."+leaf, Exposure.UNAVAILABLE, "WorldModel.ownship_navigation",
        "OwnshipNavigationSnapshot."+leaf, "Facade explicitly returns VALUE_NOT_EXPORTED; no substitute from model knowledge.")
      for leaf in ("terrain_elevation_m", "nearest_airfield", "route")),
    _blocked("ownship.navigation.formatted_coordinates", Exposure.KNOWN_BUT_NOT_EXPOSED,
        "WorldModel._format_coordinates", "OwnshipNavigationSnapshot.formatted_coordinates",
        "Derived display-only duplicate of selected position; speech uses precision-safe spoken_coordinates.",
        source="world_model_geometry", authority="derived"),
    *(_blocked("mission.units."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "MissionUnit / MissionPosition", "MissionSnapshot.units."+leaf,
        "Mission truth, not observed contacts. Unit name/ID targeting and multi-source permissions are not Foundation ownship selectors.", source="mission_store")
      for leaf in ("unit_id", "name", "updated_at", "position.latitude", "position.longitude", "position.altitude_m")),
    *(_blocked("mission.geometry."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "WorldModel._range_bearing", "RangeBearingGeometry."+leaf,
        "Deterministic two-source geometry to a mission unit, not observed range; source/target admission remains separate.",
        source="world_model_geometry", authority="derived")
      for leaf in ("range_m", "bearing_true_deg", "vertical_separation_m")),
    _blocked("mission.geometry.closure_mps", Exposure.UNAVAILABLE, "WorldModel.geometry_to_unit",
        "GeometryToUnitSnapshot.closure_mps", "Explicit VALUE_NOT_EXPORTED; cannot infer relative velocity.",
        source="world_model_geometry", authority="derived"),
    *(_blocked("mission.bridge.units."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "MissionBridgeSnapshot → CoalitionRadioDirectory", "CoalitionRadioUnit."+leaf,
        "Mission-supplied directory metadata, not cockpit tuning or sensor observation; not a Foundation ownship binding.", source="mission_bridge")
      for leaf in ("unit_id", "callsign", "recipient_type", "unit_type", "coalition", "frequency_mhz", "modulation",
                   "preset", "point.x_m", "point.z_m", "tacan_channel", "tacan_band", "aar_available", "available")),
    *(_blocked("mission.bridge.landmarks."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "MissionBridgeSnapshot → CoalitionRadioDirectory", "MissionLandmark."+leaf,
        "Mission directory, not inferred geographic truth; no Foundation ownship binding.", source="mission_bridge")
      for leaf in ("landmark_id", "name", "point.x_m", "point.z_m", "aliases")),
    *(_blocked("mission.bridge.presets."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "MissionBridgeSnapshot → NavigationChannelDirectory", "NavigationPresetChannel."+leaf,
        "Assigned channel data is not current cockpit radio; source-specific binding/admission is separate.", source="mission_bridge")
      for leaf in ("preset_id", "system", "owner_type", "owner_id", "owner_name", "channel", "frequency_mhz",
                   "frequency_khz", "modulation", "callsign", "purpose", "aircraft_type", "available")),
    *(_blocked("mission.bridge.metadata."+leaf, Exposure.KNOWN_BUT_NOT_EXPOSED,
        "MissionBridgeTelemetryStore", "MissionBridgeState."+leaf,
        "Source liveness/order/count metadata; heartbeat is NOT a new observation of each retained field.", source="mission_bridge")
      for leaf in ("connected", "stale", "last_sequence", "last_received_at", "age_seconds", "stale_after_seconds",
                   "unit_count", "landmark_count", "preset_channel_count")),
    _blocked("ownship.diagnostics.argument_changes", Exposure.RESTRICTED, "diagnosticsJson optional argument scanner",
        "state.diagnostics", "Opt-in bounded diagnostic raw argument values, not AI facts; must not leak into speech.",
        source="fa18c_cockpit", authority="observed"),
)

FACTS = (*_SAFE, *_BLOCKED, *_LEAF_AUDIT, *_METADATA_AUDIT)
REGISTRY = MappingProxyType({item.capability: item for item in FACTS})
CATALOG = tuple(item for item in FACTS if item.exposed)
CATALOG_VERSION = "orion.facts." + hashlib.sha256(
    "\n".join(item.model_dump_json() for item in FACTS).encode()).hexdigest()[:16]
MAX_FACTS = len(CATALOG)


def require_exposed(identity: str) -> FactDefinition:
    item = REGISTRY.get(identity)
    if item is None or not item.exposed:
        raise ValueError("fact_not_exposed")
    if (not item.tool or not item.presentation or not item.leaves or not item.world_key
        or not item.snapshot_field or not item.permission or not item.source or not item.authority
        or item.value_type == "number" and not item.unit):
        raise ValueError("fact_registry_incomplete")
    return item


def provider_catalog() -> list[dict[str, str]]:
    return [{"id": item.capability, "meaning": item.meaning} for item in CATALOG]
