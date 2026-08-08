from __future__ import annotations

from enum import StrEnum
import math

from pydantic import BaseModel, Field

from orion.mission import MissionPosition, MissionUnit


class ThreatAspect(StrEnum):
    HOT = "hot"
    FLANKING = "flanking"
    COLD = "cold"
    UNKNOWN = "unknown"


class RangeTrend(StrEnum):
    CLOSING = "closing"
    STABLE = "stable"
    DIVERGING = "diverging"
    UNKNOWN = "unknown"


class ThreatKinematics(BaseModel):
    aspect: ThreatAspect = ThreatAspect.UNKNOWN
    range_trend: RangeTrend = RangeTrend.UNKNOWN
    closure_kts: float | None = None
    heading_to_ownship_deg: float | None = Field(default=None, ge=0, lt=360)
    aspect_angle_deg: float | None = Field(default=None, ge=0, le=180)


def assess_threat_kinematics(unit: MissionUnit, own_position: MissionPosition) -> ThreatKinematics:
    if unit.heading_deg is None:
        return ThreatKinematics()

    bearing_to_ownship = _bearing_deg(unit.position, own_position)
    aspect_angle = _angular_difference_deg(unit.heading_deg, bearing_to_ownship)
    if aspect_angle <= 45:
        aspect = ThreatAspect.HOT
    elif aspect_angle >= 135:
        aspect = ThreatAspect.COLD
    else:
        aspect = ThreatAspect.FLANKING

    closure_kts: float | None = None
    trend = RangeTrend.UNKNOWN
    if unit.speed_mps is not None:
        closure_mps = unit.speed_mps * math.cos(math.radians(aspect_angle))
        closure_kts = round(closure_mps * 1.943844, 1)
        if closure_kts > 25:
            trend = RangeTrend.CLOSING
        elif closure_kts < -25:
            trend = RangeTrend.DIVERGING
        else:
            trend = RangeTrend.STABLE

    return ThreatKinematics(
        aspect=aspect,
        range_trend=trend,
        closure_kts=closure_kts,
        heading_to_ownship_deg=round(bearing_to_ownship, 1),
        aspect_angle_deg=round(aspect_angle, 1),
    )


def _bearing_deg(origin: MissionPosition, target: MissionPosition) -> float:
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(target.latitude)
    delta_lon = math.radians(target.longitude - origin.longitude)
    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _angular_difference_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)
