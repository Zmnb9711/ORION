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


class ClosureProfile(StrEnum):
    FAR = "far"
    MEDIUM = "medium"
    CLOSE = "close"
    FINAL = "final"
    UNKNOWN = "unknown"


class AarClosureAssessment(BaseModel):
    closure_mps: float
    band: ClosureBand
    profile: ClosureProfile
    stable_limit_mps: float
    high_limit_mps: float


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
    profile, stable_limit_mps, high_limit_mps = _profile(tanker.distance_km)
    return AarClosureAssessment(
        closure_mps=round(closure_mps, 1),
        band=_band(closure_mps, stable_limit_mps, high_limit_mps),
        profile=profile,
        stable_limit_mps=stable_limit_mps,
        high_limit_mps=high_limit_mps,
    )


def spoken_closure(assessment: AarClosureAssessment, tanker: SupportAsset, language: str) -> str:
    speed = spoken_speed(abs(assessment.closure_mps), tanker.coalition, language)
    if assessment.closure_mps < -2.0:
        return f"расхождение {speed}" if language == "ru" else f"opening at {speed}"
    return f"сближение {speed}" if language == "ru" else f"closure {speed}"


def _profile(distance_km: float | None) -> tuple[ClosureProfile, float, float]:
    """Tighten closure limits as the receiver approaches the tanker.

    Limits are stored in SI. The corresponding BLUE values are approximately:
    >3 NM: 30/60 kt, 1-3 NM: 20/40 kt, 0.5-1 NM: 10/20 kt,
    <=0.5 NM: 5/10 kt for stable/high boundaries.
    """
    if distance_km is None:
        return ClosureProfile.UNKNOWN, 15.0, 30.0
    distance_nm = distance_km / 1.852
    if distance_nm > 3.0:
        return ClosureProfile.FAR, 15.4333, 30.8667
    if distance_nm > 1.0:
        return ClosureProfile.MEDIUM, 10.2889, 20.5778
    if distance_nm > 0.5:
        return ClosureProfile.CLOSE, 5.1444, 10.2889
    return ClosureProfile.FINAL, 2.5722, 5.1444


def _band(closure_mps: float, stable_limit_mps: float, high_limit_mps: float) -> ClosureBand:
    if closure_mps < -2.0:
        return ClosureBand.OPENING
    if closure_mps <= 2.0:
        return ClosureBand.HOLD
    if closure_mps <= stable_limit_mps:
        return ClosureBand.STABLE
    if closure_mps <= high_limit_mps:
        return ClosureBand.HIGH
    return ClosureBand.EXCESSIVE
