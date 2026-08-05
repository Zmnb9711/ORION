from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Coalition(StrEnum):
    BLUE = "blue"
    RED = "red"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class UnitCategory(StrEnum):
    AIRCRAFT = "aircraft"
    HELICOPTER = "helicopter"
    GROUND = "ground"
    SHIP = "ship"
    STATIC = "static"
    UNKNOWN = "unknown"


class MissionPosition(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = 0


class MissionUnit(BaseModel):
    unit_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    coalition: Coalition = Coalition.UNKNOWN
    category: UnitCategory = UnitCategory.UNKNOWN
    type_name: str | None = None
    position: MissionPosition
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    speed_mps: float | None = Field(default=None, ge=0)
    alive: bool = True
    detected: bool = True
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MissionSnapshot(BaseModel):
    mission_id: str = Field(min_length=1)
    name: str | None = None
    theatre: str | None = None
    mission_time_s: float = Field(default=0, ge=0)
    units: list[MissionUnit] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
