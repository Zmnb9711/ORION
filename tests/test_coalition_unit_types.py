from orion.coalition_radio import (
    CoalitionRadioDirectory,
    CoalitionRadioUnit,
    MissionLandmark,
    MissionPoint,
    NearbyCallsignQuery,
)
from orion.dcs_capabilities import DcsRecipientType


def test_nearby_callsign_report_includes_concrete_unit_type() -> None:
    directory = CoalitionRadioDirectory()
    directory.replace_landmarks([
        MissionLandmark(
            landmark_id="aleppo",
            name="Aleppo",
            aliases=["Алеппо"],
            point=MissionPoint(x_m=0, z_m=0),
        )
    ])
    directory.replace([
        CoalitionRadioUnit(
            unit_id="colt-1",
            callsign="Colt 1",
            recipient_type=DcsRecipientType.COALITION_AIRCRAFT,
            unit_type="F/A-18C",
            coalition="blue",
            point=MissionPoint(x_m=12000, z_m=0),
        )
    ])

    result = directory.lookup_near_landmark(
        NearbyCallsignQuery(landmark="Алеппо", coalition="blue")
    )

    assert result.found is True
    assert result.units[0].unit.unit_type == "F/A-18C"
    assert "Colt 1, F/A-18C" in result.message


def test_broad_recipient_type_is_used_when_dcs_type_is_missing() -> None:
    unit = CoalitionRadioUnit(
        unit_id="alpha",
        callsign="Alpha",
        recipient_type=DcsRecipientType.COALITION_GROUND,
        coalition="blue",
    )

    assert unit.spoken_type == "coalition_ground"
