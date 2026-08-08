from __future__ import annotations

from dataclasses import dataclass

from orion.mission import Coalition


@dataclass(frozen=True)
class DisplaySpeed:
    value: float
    unit: str


def display_speed(speed_mps: float, coalition: Coalition | str | None) -> DisplaySpeed:
    """Keep internal physics in SI, convert only for pilot-facing presentation.

    Blue coalition follows western aviation convention: knots.
    Red coalition uses kilometers per hour.
    Unknown/neutral data stays in m/s so ORION does not guess a convention.
    """
    normalized = coalition.value if isinstance(coalition, Coalition) else (coalition or "").casefold()
    if normalized == Coalition.BLUE.value:
        return DisplaySpeed(value=speed_mps * 1.9438444924406, unit="kt")
    if normalized == Coalition.RED.value:
        return DisplaySpeed(value=speed_mps * 3.6, unit="km/h")
    return DisplaySpeed(value=speed_mps, unit="m/s")


def spoken_speed(speed_mps: float, coalition: Coalition | str | None, language: str) -> str:
    speed = display_speed(speed_mps, coalition)
    value = round(speed.value)
    if speed.unit == "kt":
        return f"{value} узлов" if language == "ru" else f"{value} knots"
    if speed.unit == "km/h":
        return f"{value} километров в час" if language == "ru" else f"{value} kilometers per hour"
    return f"{value} метров в секунду" if language == "ru" else f"{value} meters per second"
