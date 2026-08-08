from __future__ import annotations

from math import atan2, cos, degrees, radians, sin, sqrt

from pydantic import BaseModel

from orion.mission_context import LiveMissionContext, SupportAsset


class AarInterceptGuidance(BaseModel):
    intercept_heading_deg: float
    eta_s: float
    intercept_distance_km: float


def compute_intercept_guidance(context: LiveMissionContext, tanker: SupportAsset) -> AarInterceptGuidance | None:
    """Solve a constant-velocity 2D intercept without inventing missing inputs."""
    own = context.ownship
    if (
        own is None
        or own.true_airspeed_mps is None
        or own.true_airspeed_mps <= 0
        or tanker.latitude is None
        or tanker.longitude is None
        or tanker.heading_deg is None
        or tanker.speed_mps is None
    ):
        return None

    lat0 = radians(own.latitude)
    north_m = radians(tanker.latitude - own.latitude) * 6_371_008.8
    east_m = radians(tanker.longitude - own.longitude) * 6_371_008.8 * cos(lat0)
    heading_rad = radians(tanker.heading_deg)
    tanker_east_mps = tanker.speed_mps * sin(heading_rad)
    tanker_north_mps = tanker.speed_mps * cos(heading_rad)
    own_speed_mps = own.true_airspeed_mps

    a = tanker_east_mps**2 + tanker_north_mps**2 - own_speed_mps**2
    b = 2.0 * (east_m * tanker_east_mps + north_m * tanker_north_mps)
    c = east_m**2 + north_m**2

    if c < 1.0:
        return AarInterceptGuidance(
            intercept_heading_deg=round(own.heading_deg or 0.0, 1),
            eta_s=0.0,
            intercept_distance_km=0.0,
        )

    roots: list[float] = []
    if abs(a) < 1e-9:
        if abs(b) > 1e-9:
            roots = [-c / b]
    else:
        discriminant = b**2 - 4.0 * a * c
        if discriminant >= 0:
            root = sqrt(discriminant)
            roots = [(-b - root) / (2.0 * a), (-b + root) / (2.0 * a)]

    positive_roots = [value for value in roots if value > 0]
    if not positive_roots:
        return None

    eta_s = min(positive_roots)
    intercept_east_m = east_m + tanker_east_mps * eta_s
    intercept_north_m = north_m + tanker_north_mps * eta_s
    intercept_heading_deg = (degrees(atan2(intercept_east_m, intercept_north_m)) + 360.0) % 360.0
    return AarInterceptGuidance(
        intercept_heading_deg=round(intercept_heading_deg, 1),
        eta_s=round(eta_s, 1),
        intercept_distance_km=round(own_speed_mps * eta_s / 1000.0, 1),
    )
