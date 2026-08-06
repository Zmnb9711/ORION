from datetime import UTC, datetime

from orion.coalition_radio import CoalitionRadioUnit, MissionLandmark, MissionPoint, coalition_radio
from orion.dcs_capabilities import DcsRecipientType
from orion.mission_bridge_ingest import (
    MissionBridgeDelta,
    MissionBridgeHeartbeat,
    MissionBridgeSnapshot,
    MissionBridgeTelemetryStore,
)


def unit(unit_id: str, callsign: str) -> CoalitionRadioUnit:
    return CoalitionRadioUnit(
        unit_id=unit_id,
        callsign=callsign,
        recipient_type=DcsRecipientType.COALITION_AIRCRAFT,
        unit_type="F/A-18C",
        coalition="blue",
        point=MissionPoint(x_m=0, z_m=0),
    )


def test_delta_updates_and_removes_units() -> None:
    store = MissionBridgeTelemetryStore()
    first = store.ingest(
        MissionBridgeSnapshot(
            session_id="mission-1",
            mission_name="Test",
            player_callsign="Ford 1-1",
            sequence=1,
            generated_at=datetime.now(UTC),
            units=[unit("u1", "Ford 2-1")],
            landmarks=[MissionLandmark(landmark_id="aleppo", name="Aleppo", point=MissionPoint(x_m=0, z_m=0))],
        )
    )
    assert first.accepted

    result = store.apply_delta(
        MissionBridgeDelta(
            session_id="mission-1",
            sequence=2,
            generated_at=datetime.now(UTC),
            remove_unit_ids=["u1"],
            upsert_units=[unit("u2", "Colt 1-1")],
        )
    )

    assert result.accepted
    assert result.state.unit_count == 1
    assert [item.unit_id for item in coalition_radio.list()] == ["u2"]
    store.disconnect(clear_indexes=True)


def test_heartbeat_advances_sequence_without_replacing_indexes() -> None:
    store = MissionBridgeTelemetryStore()
    store.ingest(
        MissionBridgeSnapshot(
            session_id="mission-2",
            sequence=5,
            generated_at=datetime.now(UTC),
            units=[unit("u1", "Ford 2-1")],
        )
    )

    result = store.heartbeat(
        MissionBridgeHeartbeat(
            session_id="mission-2",
            sequence=6,
            generated_at=datetime.now(UTC),
        )
    )

    assert result.accepted
    assert result.state.last_sequence == 6
    assert result.state.unit_count == 1
    assert result.state.player_callsign is None
    store.disconnect(clear_indexes=True)


def test_stale_or_duplicate_delta_is_rejected() -> None:
    store = MissionBridgeTelemetryStore()
    store.ingest(
        MissionBridgeSnapshot(
            session_id="mission-3",
            sequence=10,
            generated_at=datetime.now(UTC),
        )
    )

    result = store.apply_delta(
        MissionBridgeDelta(
            session_id="mission-3",
            sequence=10,
            generated_at=datetime.now(UTC),
        )
    )

    assert not result.accepted
    assert result.duplicate_or_stale
    store.disconnect(clear_indexes=True)


def test_openapi_contains_live_update_routes() -> None:
    from orion.app import app

    paths = app.openapi()["paths"]
    assert "/v1/mission-bridge/delta" in paths
    assert "/v1/mission-bridge/heartbeat" in paths
    assert "/v1/mission-bridge/stale-timeout" in paths
