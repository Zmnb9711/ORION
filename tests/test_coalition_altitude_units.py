from __future__ import annotations

from orion.coalition_units import display_altitude, spoken_altitude
from orion.mission import Coalition


def test_blue_altitude_is_presented_in_feet() -> None:
    altitude = display_altitude(1000.0, Coalition.BLUE)
    assert altitude.unit == "ft"
    assert round(altitude.value) == 3281
    assert spoken_altitude(1000.0, Coalition.BLUE, "ru") == "3281 футов"


def test_red_altitude_is_presented_in_meters() -> None:
    altitude = display_altitude(1000.0, Coalition.RED)
    assert altitude.unit == "m"
    assert altitude.value == 1000.0
    assert spoken_altitude(1000.0, Coalition.RED, "ru") == "1000 метров"


def test_unknown_altitude_is_presented_in_feet() -> None:
    altitude = display_altitude(1000.0, Coalition.UNKNOWN)
    assert altitude.unit == "ft"
    assert round(altitude.value) == 3281
    assert spoken_altitude(1000.0, Coalition.UNKNOWN, "ru") == "3281 футов"
