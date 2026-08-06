from fastapi.testclient import TestClient

from orion.app import app
from orion.coalition_radio import (
    CoalitionRadioDirectory,
    CoalitionRadioUnit,
    MissionLandmark,
    MissionPoint,
    NearbyCallsignQuery,
)
from orion.dcs_capabilities import DcsRecipientType
from orion.voice_understanding import parse_transcript


def test_callsigns_are_sorted_by_distance_from_landmark() -> None:
    directory = CoalitionRadioDirectory()
    directory.replace_landmarks(
        [MissionLandmark(landmark_id="aleppo", name="Aleppo", aliases=["Алеппо"], point=MissionPoint(x_m=0, z_m=0))]
    )
    directory.replace(
        [
            CoalitionRadioUnit(
                unit_id="far",
                callsign="Pontiac 2",
                recipient_type=DcsRecipientType.COALITION_AIRCRAFT,
                coalition="blue",
                point=MissionPoint(x_m=30000, z_m=40000),
            ),
            CoalitionRadioUnit(
                unit_id="near",
                callsign="Colt 1",
                recipient_type=DcsRecipientType.COALITION_AIRCRAFT,
                coalition="blue",
                point=MissionPoint(x_m=3000, z_m=4000),
            ),
        ]
    )

    result = directory.lookup_near_landmark(
        NearbyCallsignQuery(landmark="Алеппо", radius_km=60, coalition="blue")
    )

    assert result.found is True
    assert [item.unit.callsign for item in result.units] == ["Colt 1", "Pontiac 2"]
    assert [item.distance_km for item in result.units] == [5.0, 50.0]


def test_units_without_position_are_not_invented_as_nearby() -> None:
    directory = CoalitionRadioDirectory()
    directory.replace_landmarks(
        [MissionLandmark(landmark_id="damascus", name="Damascus", point=MissionPoint(x_m=0, z_m=0))]
    )
    directory.replace(
        [
            CoalitionRadioUnit(
                unit_id="unknown-position",
                callsign="Texaco 1",
                recipient_type=DcsRecipientType.TANKER,
                coalition="blue",
            )
        ]
    )

    result = directory.lookup_near_landmark(NearbyCallsignQuery(landmark="Damascus"))

    assert result.found is False
    assert result.units == []


def test_nearby_callsign_phrase_is_recognized() -> None:
    parsed = parse_transcript("Кто у нас рядом с Дамаском?")
    assert parsed.commands[0].intent == "find_unit_callsigns_near_landmark"


def test_landmark_routes_are_available() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/coalition-control/landmarks" in paths
    assert "/v1/coalition-control/callsigns/near-landmark" in paths
