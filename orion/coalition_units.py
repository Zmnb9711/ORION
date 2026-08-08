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


@dataclass(frozen=True)
class DisplayAltitude:
    value: float
    unit: str


def _normalized_coalition(coalition: Coalition | str | None) -> str:
    return coalition.value if isinstance(coalition, Coalition) else (coalition or "").casefold()


def _uses_imperial_aviation_units(coalition: Coalition | str | None) -> bool:
    normalized = _normalized_coalition(coalition)
    return normalized in {Coalition.BLUE.value, Coalition.UNKNOWN.value}


def display_speed(speed_mps: float, coalition: Coalition | str | None) -> DisplaySpeed:
    """Keep internal physics in SI; BLUE and UNKNOWN are pilot-facing aviation units."""
    normalized = _normalized_coalition(coalition)
    if _uses_imperial_aviation_units(coalition):
        return DisplaySpeed(value=speed_mps * 1.9438444924406, unit="kt")
    if normalized == Coalition.RED.value:
        return DisplaySpeed(value=speed_mps * 3.6, unit="km/h")
    return DisplaySpeed(value=speed_mps, unit="m/s")


def display_distance(distance_km: float, coalition: Coalition | str | None) -> DisplayDistance:
    """Keep geometry internally in metric; BLUE and UNKNOWN are shown in nautical miles."""
    if _uses_imperial_aviation_units(coalition):
        return DisplayDistance(value=distance_km / 1.852, unit="NM")
    return DisplayDistance(value=distance_km, unit="km")


def display_altitude(altitude_m: float, coalition: Coalition | str | None) -> DisplayAltitude:
    """Keep altitude internally in meters; BLUE and UNKNOWN are shown in feet."""
    if _uses_imperial_aviation_units(coalition):
        return DisplayAltitude(value=altitude_m * 3.2808398950131, unit="ft")
    return DisplayAltitude(value=altitude_m, unit="m")


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


def spoken_altitude(altitude_m: float, coalition: Coalition | str | None, language: str) -> str:
    altitude = display_altitude(altitude_m, coalition)
    value = round(altitude.value)
    if altitude.unit == "ft":
        return f"{value} футов" if language == "ru" else f"{value} feet"
    return f"{value} метров" if language == "ru" else f"{value} meters"
