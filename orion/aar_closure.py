from __future__ import annotations

from enum import StrEnum
from math import cos, radians, sin

from pydantic import BaseModel

from orion.coalition_units import spoken_speed
from orion.mission_context import LiveMissionContext, SupportAsset


class ClosureBand(StrEnum):
    OPENING = "opening"
    HOLD = "hold"
    STABLE = "stable"
    HIGH = "high"
    EXCESSIVE = "excessive"


class AarClosureAssessment(BaseModel):
    closure_mps: float
    band: ClosureBand


def compute_closure(context: LiveMissionContext, tanker: SupportAsset) -> AarClosureAssessment | None:
    """Return positive line-of-sight closure when ownship is closing on the tanker."""
    own = context.ownship
    if (
        own is None
        or own.heading_deg is None
        or own.true_airspeed_mps is None
        or tanker.heading_deg is None
        or tanker.speed_mps is None
        or tanker.bearing_deg is None
    ):
        return None

    own_heading = radians(own.heading_deg)
    tanker_heading = radians(tanker.heading_deg)
    bearing = radians(tanker.bearing_deg)

    own_east = own.true_airspeed_mps * sin(own_heading)
    own_north = own.true_airspeed_mps * cos(own_heading)
    tanker_east = tanker.speed_mps * sin(tanker_heading)
    tanker_north = tanker.speed_mps * cos(tanker_heading)

    los_east = sin(bearing)
    los_north = cos(bearing)
    relative_radial_mps = (tanker_east - own_east) * los_east + (tanker_north - own_north) * los_north
    closure_mps = -relative_radial_mps
    return AarClosureAssessment(closure_mps=round(closure_mps, 1), band=_band(closure_mps))


def spoken_closure(assessment: AarClosureAssessment, tanker: SupportAsset, language: str) -> str:
    speed = spoken_speed(abs(assessment.closure_mps), tanker.coalition, language)
    if assessment.closure_mps < -2.0:
        return f"расхождение {speed}" if language == "ru" else f"opening at {speed}"
    return f"сближение {speed}" if language == "ru" else f"closure {speed}"


def _band(closure_mps: float) -> ClosureBand:
    if closure_mps < -2.0:
        return ClosureBand.OPENING
    if closure_mps <= 2.0:
        return ClosureBand.HOLD
    if closure_mps <= 15.0:
        return ClosureBand.STABLE
    if closure_mps <= 30.0:
        return ClosureBand.HIGH
    return ClosureBand.EXCESSIVE
