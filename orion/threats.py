from __future__ import annotations

from enum import StrEnum
from math import asin, atan2, cos, degrees, radians, sin, sqrt

from pydantic import BaseModel, Field

from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory

EARTH_RADIUS_M = 6_371_000.0


class ThreatLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ThreatAssessment(BaseModel):
    unit_id: str
    name: str
    level: ThreatLevel
    score: float = Field(ge=0, le=100)
    distance_m: float = Field(ge=0)
    bearing_deg: float = Field(ge=0, lt=360)
    closure_mps: float | None = None
    predicted_position: MissionPosition
    reasons: list[str] = Field(default_factory=list)


def distance_and_bearing(origin: MissionPosition, target: MissionPosition) -> tuple[float, float]:
    lat1 = radians(origin.latitude)
    lat2 = radians(target.latitude)
    delta_lat = lat2 - lat1
    delta_lon = radians(target.longitude - origin.longitude)

    a = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    distance = 2 * EARTH_RADIUS_M * asin(min(1.0, sqrt(a)))

    y = sin(delta_lon) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(delta_lon)
    bearing = (degrees(atan2(y, x)) + 360.0) % 360.0
    return distance, bearing


def predict_position(unit: MissionUnit, horizon_s: float) -> MissionPosition:
    speed = unit.speed_mps or 0.0
    heading = radians(unit.heading_deg or 0.0)
    distance = speed * horizon_s
    angular_distance = distance / EARTH_RADIUS_M
    lat1 = radians(unit.position.latitude)
    lon1 = radians(unit.position.longitude)

    lat2 = asin(
        sin(lat1) * cos(angular_distance)
        + cos(lat1) * sin(angular_distance) * cos(heading)
    )
    lon2 = lon1 + atan2(
        sin(heading) * sin(angular_distance) * cos(lat1),
        cos(angular_distance) - sin(lat1) * sin(lat2),
    )

    return MissionPosition(
        latitude=degrees(lat2),
        longitude=((degrees(lon2) + 540.0) % 360.0) - 180.0,
        altitude_m=unit.position.altitude_m,
    )


def _category_weight(category: UnitCategory) -> float:
    return {
        UnitCategory.AIRCRAFT: 30.0,
        UnitCategory.HELICOPTER: 20.0,
        UnitCategory.GROUND: 18.0,
        UnitCategory.SHIP: 22.0,
        UnitCategory.STATIC: 5.0,
        UnitCategory.UNKNOWN: 10.0,
    }[category]


def assess_threats(
    snapshot: MissionSnapshot,
    own_position: MissionPosition,
    own_coalition: Coalition = Coalition.BLUE,
    horizon_s: float = 60.0,
) -> list[ThreatAssessment]:
    assessments: list[ThreatAssessment] = []

    for unit in snapshot.units:
        if not unit.alive or not unit.detected or unit.coalition in {own_coalition, Coalition.NEUTRAL}:
            continue

        distance_m, bearing_deg = distance_and_bearing(own_position, unit.position)
        distance_score = max(0.0, 45.0 * (1.0 - min(distance_m, 150_000.0) / 150_000.0))
        speed_score = min((unit.speed_mps or 0.0) / 350.0 * 15.0, 15.0)
        score = min(100.0, _category_weight(unit.category) + distance_score + speed_score)

        reasons = [f"distance {distance_m / 1000:.1f} km", f"category {unit.category.value}"]
        if (unit.speed_mps or 0.0) > 200:
            reasons.append("high speed")
        if distance_m < 25_000:
            reasons.append("close proximity")

        if score >= 80:
            level = ThreatLevel.CRITICAL
        elif score >= 60:
            level = ThreatLevel.HIGH
        elif score >= 35:
            level = ThreatLevel.MEDIUM
        else:
            level = ThreatLevel.LOW

        assessments.append(
            ThreatAssessment(
                unit_id=unit.unit_id,
                name=unit.name,
                level=level,
                score=round(score, 1),
                distance_m=round(distance_m, 1),
                bearing_deg=round(bearing_deg, 1),
                closure_mps=unit.speed_mps,
                predicted_position=predict_position(unit, horizon_s),
                reasons=reasons,
            )
        )

    return sorted(assessments, key=lambda item: (-item.score, item.distance_m))
