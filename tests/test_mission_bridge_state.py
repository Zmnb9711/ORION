from orion.coalition_radio import MissionLandmark, MissionPoint, coalition_radio
from orion.dcs_capabilities import DcsRecipientType
from orion.mission_bridge_state import MissionBridgeSnapshot, MissionBridgeState
from orion.coalition_radio import CoalitionRadioUnit


def _snapshot(sequence: int, session_id: str = "mission-1") -> MissionBridgeSnapshot:
    return MissionBridgeSnapshot(
        session_id=session_id,
        sequence=sequence,
        mission_name="Syria Test",
        player_callsign="Springfield 1-1",
        units=[
            CoalitionRadioUnit(
                unit_id="colt-1",
                callsign="Colt 1",
                recipient_type=DcsRecipientType.COALITION_AIRCRAFT,
                unit_type="F/A-18C",
                coalition="blue",
                point=MissionPoint(x_m=1000, z_m=2000),
            )
        ],
        landmarks=[
            MissionLandmark(
                landmark_id="aleppo",
                name="Aleppo",
                point=MissionPoint(x_m=0, z_m=0),
            )
        ],
    )


def test_snapshot_updates_bridge_status_and_directory() -> None:
    state = MissionBridgeState()
    result = state.apply(_snapshot(1))

    assert result.accepted is True
    assert result.status.connected is True
    assert result.status.player_callsign == "Springfield 1-1"
    assert result.status.unit_count == 1
    assert coalition_radio.list()[0].unit_type == "F/A-18C"
    assert coalition_radio.list_landmarks()[0].name == "Aleppo"


def test_stale_sequence_is_rejected_for_same_session() -> None:
    state = MissionBridgeState()
    state.apply(_snapshot(3))

    result = state.apply(_snapshot(2))

    assert result.accepted is False
    assert result.status.last_sequence == 3


def test_new_session_can_restart_sequence() -> None:
    state = MissionBridgeState()
    state.apply(_snapshot(5, "mission-1"))

    result = state.apply(_snapshot(0, "mission-2"))

    assert result.accepted is True
    assert result.status.session_id == "mission-2"
    assert result.status.last_sequence == 0


def test_disconnect_preserves_last_snapshot_metadata() -> None:
    state = MissionBridgeState()
    state.apply(_snapshot(1))

    status = state.disconnect()

    assert status.connected is False
    assert status.mission_name == "Syria Test"
    assert status.unit_count == 1
