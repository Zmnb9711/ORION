from __future__ import annotations

from dataclasses import dataclass

from orion.mission import Coalition


@dataclass(frozen=True)
class DisplaySpeed:
    value: float
    unit: str


@dataclass(frozen=True)
class DisplayDistance:
    value: float
    unit: str


def _normalized_coalition(coalition: Coalition | str | None) -> str:
    return coalition.value if isinstance(coalition, Coalition) else (coalition or "").casefold()


def display_speed(speed_mps: float, coalition: Coalition | str | None) -> DisplaySpeed:
    """Keep internal physics in SI, convert only for pilot-facing presentation."""
    normalized = _normalized_coalition(coalition)
    if normalized == Coalition.BLUE.value:
        return DisplaySpeed(value=speed_mps * 1.9438444924406, unit="kt")
    if normalized == Coalition.RED.value:
        return DisplaySpeed(value=speed_mps * 3.6, unit="km/h")
    return DisplaySpeed(value=speed_mps, unit="m/s")


def display_distance(distance_km: float, coalition: Coalition | str | None) -> DisplayDistance:
    """Keep geometry in kilometers/meters; convert only for pilot-facing presentation.

    Blue coalition follows western aviation convention: nautical miles.
    Red coalition uses kilometers. Unknown/neutral remains kilometers so ORION
    does not invent a coalition convention.
    """
    normalized = _normalized_coalition(coalition)
    if normalized == Coalition.BLUE.value:
        return DisplayDistance(value=distance_km / 1.852, unit="NM")
    return DisplayDistance(value=distance_km, unit="km")


def spoken_speed(speed_mps: float, coalition: Coalition | str | None, language: str) -> str:
    speed = display_speed(speed_mps, coalition)
    value = round(speed.value)
    if speed.unit == "kt":
        return f"{value} узлов" if language == "ru" else f"{value} knots"
    if speed.unit == "km/h":
        return f"{value} километров в час" if language == "ru" else f"{value} kilometers per hour"
    return f"{value} метров в секунду" if language == "ru" else f"{value} meters per second"


def spoken_distance(distance_km: float, coalition: Coalition | str | None, language: str) -> str:
    distance = display_distance(distance_km, coalition)
    if distance.unit == "NM":
        return f"{distance.value:.1f} морских миль" if language == "ru" else f"{distance.value:.1f} nautical miles"
    return f"{distance.value:.1f} километра" if language == "ru" else f"{distance.value:.1f} kilometers"
