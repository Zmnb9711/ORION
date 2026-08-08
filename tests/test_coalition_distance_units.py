from __future__ import annotations

import orion.voice_mission_context_queries as mission_voice
from orion.coalition_units import display_distance, spoken_distance
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, MissionContact, OwnshipContext, SupportAsset


def test_blue_distance_is_presented_in_nautical_miles() -> None:
    distance = display_distance(18.52, Coalition.BLUE)
    assert distance.unit == "NM"
    assert round(distance.value, 1) == 10.0
    assert spoken_distance(18.52, Coalition.BLUE, "ru") == "10.0 морских миль"


def test_red_distance_is_presented_in_kilometers() -> None:
    distance = display_distance(18.52, Coalition.RED)
    assert distance.unit == "km"
    assert distance.value == 18.52
    assert spoken_distance(18.52, Coalition.RED, "ru") == "18.5 километра"


def test_unknown_distance_is_presented_in_nautical_miles() -> None:
    distance = display_distance(18.52, Coalition.UNKNOWN)
    assert distance.unit == "NM"
    assert round(distance.value, 1) == 10.0


def test_blue_tanker_brief_uses_nautical_miles(monkeypatch) -> None:
    context = LiveMissionContext(
        available=True,
        ownship=OwnshipContext(aircraft_type="FA-18C_hornet", latitude=41.0, longitude=41.0, altitude_m=5000, true_airspeed_mps=250),
        tankers=[SupportAsset(unit_id="t1", callsign="Texaco", role=DcsRecipientType.TANKER, coalition=Coalition.BLUE, latitude=41.0, longitude=41.2, altitude_m=7000, distance_km=18.52, bearing_deg=90, heading_deg=90, speed_mps=150, aar_available=True)],
    )
    monkeypatch.setattr(mission_voice, "build_live_mission_context", lambda: context)
    result = mission_voice.execute_mission_context_query("find_tanker", "Найди танкер")
    assert "10.0 морских миль" in result.spoken_text
    assert "18.5 километра" not in result.spoken_text


def test_red_contact_brief_keeps_kilometers(monkeypatch) -> None:
    context = LiveMissionContext(
        available=True,
        hostiles=[MissionContact(unit_id="r1", name="Bandit", coalition=Coalition.RED, latitude=41.0, longitude=41.1, altitude_m=6000, speed_mps=200, distance_km=18.52, bearing_deg=90)],
    )
    monkeypatch.setattr(mission_voice, "build_live_mission_context", lambda: context)
    result = mission_voice.execute_mission_context_query("nearest_hostile", "Ближайший противник")
    assert "18.5 километра" in result.spoken_text
    assert "морских миль" not in result.spoken_text
