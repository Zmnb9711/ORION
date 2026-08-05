from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Position(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float


class AircraftState(BaseModel):
    aircraft_type: str = Field(min_length=1)
    callsign: str | None = None
    position: Position
    heading_deg: float = Field(ge=0, lt=360)
    true_airspeed_mps: float = Field(ge=0)
    vertical_speed_mps: float = 0
    fuel_fraction: float | None = Field(default=None, ge=0, le=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TelemetryEnvelope(BaseModel):
    protocol_version: str = "0.1"
    source: str = "dcs-export"
    state: AircraftState
