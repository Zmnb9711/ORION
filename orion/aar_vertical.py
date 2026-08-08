from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from orion.coalition_units import spoken_altitude
from orion.mission_context import LiveMissionContext, SupportAsset


class VerticalBand(StrEnum):
    LOW = "low"
    ALIGNED = "aligned"
    HIGH = "high"


class AarVerticalAssessment(BaseModel):
    offset_m: float
    band: VerticalBand


def compute_vertical(context: LiveMissionContext, tanker: SupportAsset) -> AarVerticalAssessment | None:
    own = context.ownship
    if own is None or own.altitude_m is None or tanker.altitude_m is None:
        return None
    offset_m = own.altitude_m - tanker.altitude_m
    return AarVerticalAssessment(offset_m=round(offset_m, 1), band=_band(offset_m, tanker.distance_km))


def spoken_vertical(assessment: AarVerticalAssessment, tanker: SupportAsset, language: str) -> str:
    amount = spoken_altitude(abs(assessment.offset_m), tanker.coalition, language)
    if assessment.band == VerticalBand.HIGH:
        return f"выше танкера на {amount}" if language == "ru" else f"{amount} above tanker"
    if assessment.band == VerticalBand.LOW:
        return f"ниже танкера на {amount}" if language == "ru" else f"{amount} below tanker"
    return f"по высоте в допуске, отклонение {amount}" if language == "ru" else f"altitude aligned, offset {amount}"


def _band(offset_m: float, distance_km: float | None) -> VerticalBand:
    # Tighten altitude matching as the receiver approaches the tanker.
    if distance_km is None:
        tolerance_m = 150.0
    elif distance_km > 5.556:  # > 3 NM
        tolerance_m = 300.0
    elif distance_km > 1.852:  # 1-3 NM
        tolerance_m = 150.0
    elif distance_km > 0.926:  # 0.5-1 NM
        tolerance_m = 75.0
    else:
        tolerance_m = 30.0
    if offset_m > tolerance_m:
        return VerticalBand.HIGH
    if offset_m < -tolerance_m:
        return VerticalBand.LOW
    return VerticalBand.ALIGNED
