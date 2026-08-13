from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Position(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float
    altitude_agl_m: float | None = Field(default=None, ge=0)


class Attitude(BaseModel):
    pitch_deg: float | None = None
    bank_deg: float | None = None
    yaw_deg: float | None = None


class VelocityVector(BaseModel):
    x_mps: float | None = None
    y_mps: float | None = None
    z_mps: float | None = None


class AirframeState(BaseModel):
    gear: dict[str, object] | None = None
    flaps: dict[str, object] | None = None
    speedbrakes: dict[str, object] | None = None
    hook: dict[str, object] | None = None
    wing: dict[str, object] | None = None
    canopy: dict[str, object] | None = None
    refueling: dict[str, object] | None = None
    wheelbrakes: dict[str, object] | None = None


class PropulsionState(BaseModel):
    rpm: dict[str, float | None] | None = None
    temperature: dict[str, float | None] | None = None
    fuel_consumption: dict[str, float | None] | None = None
    hydraulic_pressure: dict[str, float | None] | None = None


class AircraftState(BaseModel):
    aircraft_type: str = Field(min_length=1)
    callsign: str | None = None
    position: Position
    heading_deg: float = Field(ge=0, lt=360)
    true_airspeed_mps: float = Field(ge=0)
    vertical_speed_mps: float = 0
    fuel_fraction: float | None = Field(default=None, ge=0, le=1)
    attitude: Attitude | None = None
    velocity_vector: VelocityVector | None = None
    airframe: AirframeState | None = None
    propulsion: PropulsionState | None = None
    navigation: dict[str, object] | None = None
    radios: dict[str, object] | None = None
    payload: dict[str, object] | None = None
    warnings: dict[str, object] | None = None
    ew: dict[str, object] | None = None
    sensors: dict[str, object] | None = None
    capabilities: dict[str, str] | None = None
    cockpit_state: dict[str, object] | None = None
    diagnostics: dict[str, object] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TelemetryEnvelope(BaseModel):
    protocol_version: str = "0.1"
    source: str = "dcs-export"
    sequence: int | None = Field(default=None, ge=0)
    captured_at: datetime | None = None
    model_time_s: float | None = Field(default=None, ge=0)
    state: AircraftState
