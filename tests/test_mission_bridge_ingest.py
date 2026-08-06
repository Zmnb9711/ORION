from datetime import UTC, datetime

from orion.coalition_radio import CoalitionRadioUnit, MissionLandmark, MissionPoint, NearbyCallsignQuery, coalition_radio
from orion.dcs_capabilities import DcsRecipientType
from orion.mission_bridge_ingest import MissionBridgeSnapshot, MissionBridgeTelemetryStore


def _snapshot(sequence: int) -> MissionBridgeSnapshot:
    return MissionBridgeSnapshot(
        session_id="flight-1",
        mission_name="Syria Test",
        sequence=sequence,
        generated_at=datetime.now(UTC),
        units=[
            CoalitionRadioUnit(
                unit_id="colt-1",
                callsign="Colt 1",
                unit_type="F/A-18C",
                recipient_type=DcsRecipientType.COALITION_AIRCRAFT,
                coalition="blue",
                point=MissionPoint(x_m=10_000, z_m=0),
            )
        ],
        landmarks=[
            MissionLandmark(
                landmark_id="aleppo",
                name="Aleppo",
                point=MissionPoint(x_m=0, z_m=0),
                aliases=["Алеппо"],
            )
        ],
    )


def test_snapshot_updates_live_mission_indexes() -> None:
    store = MissionBridgeTelemetryStore()
    result = store.ingest(_snapshot(1))

    assert result.accepted is True
    assert result.state.connected is True
    assert result.state.unit_count == 1
    nearby = coalition_radio.lookup_near_landmark(NearbyCallsignQuery(landmark="Алеппо"))
    assert nearby.found is True
    assert nearby.units[0].unit.unit_type == "F/A-18C"


def test_stale_snapshot_is_rejected() -> None:
    store = MissionBridgeTelemetryStore()
    store.ingest(_snapshot(5))
    result = store.ingest(_snapshot(4))

    assert result.accepted is False
    assert result.duplicate_or_stale is True
    assert result.state.last_sequence == 5


def test_new_session_may_restart_sequence() -> None:
    store = MissionBridgeTelemetryStore()
    store.ingest(_snapshot(5))
    next_session = _snapshot(0).model_copy(update={"session_id": "flight-2"})

    result = store.ingest(next_session)

    assert result.accepted is True
    assert result.state.session_id == "flight-2"
    assert result.state.last_sequence == 0


def test_disconnect_clears_live_indexes() -> None:
    store = MissionBridgeTelemetryStore()
    store.ingest(_snapshot(1))
    state = store.disconnect(session_id="flight-1")

    assert state.connected is False
    assert coalition_radio.list() == []
    assert coalition_radio.list_landmarks() == []
