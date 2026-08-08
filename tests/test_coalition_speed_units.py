from __future__ import annotations

import orion.voice_mission_context_queries as mission_voice
from orion.coalition_units import display_speed, spoken_speed
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, MissionContact, OwnshipContext, SupportAsset


def test_blue_speed_is_presented_in_knots() -> None:
    speed = display_speed(100.0, Coalition.BLUE)
    assert speed.unit == "kt"
    assert round(speed.value) == 194
    assert spoken_speed(100.0, Coalition.BLUE, "ru") == "194 узлов"


def test_red_speed_is_presented_in_kilometers_per_hour() -> None:
    speed = display_speed(100.0, Coalition.RED)
    assert speed.unit == "km/h"
    assert speed.value == 360.0
    assert spoken_speed(100.0, Coalition.RED, "ru") == "360 километров в час"


def test_unknown_coalition_keeps_si_without_guessing() -> None:
    speed = display_speed(100.0, Coalition.UNKNOWN)
    assert speed.unit == "m/s"
    assert speed.value == 100.0


def test_blue_tanker_voice_brief_uses_knots(monkeypatch) -> None:
    context = LiveMissionContext(
        available=True,
        ownship=OwnshipContext(aircraft_type="FA-18C_hornet", latitude=41.0, longitude=41.0, altitude_m=5000, true_airspeed_mps=250),
        tankers=[SupportAsset(unit_id="t1", callsign="Texaco", role=DcsRecipientType.TANKER, coalition=Coalition.BLUE, latitude=41.0, longitude=41.2, altitude_m=7000, distance_km=16.8, bearing_deg=90, heading_deg=90, speed_mps=150, aar_available=True)],
    )
    monkeypatch.setattr(mission_voice, "build_live_mission_context", lambda: context)
    result = mission_voice.execute_mission_context_query("find_tanker", "Найди танкер")
    assert "292 узлов" in result.spoken_text
    assert "метров в секунду" not in result.spoken_text


def test_red_contact_voice_brief_uses_kmh(monkeypatch) -> None:
    context = LiveMissionContext(
        available=True,
        hostiles=[MissionContact(unit_id="r1", name="Bandit", coalition=Coalition.RED, latitude=41.0, longitude=41.1, altitude_m=6000, speed_mps=200, distance_km=8.4, bearing_deg=90)],
    )
    monkeypatch.setattr(mission_voice, "build_live_mission_context", lambda: context)
    result = mission_voice.execute_mission_context_query("nearest_hostile", "Ближайший противник")
    assert "720 километров в час" in result.spoken_text
    assert "узлов" not in result.spoken_text
