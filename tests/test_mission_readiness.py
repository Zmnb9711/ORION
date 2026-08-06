from datetime import UTC, datetime

import pytest

from orion.mission_bridge_ingest import MissionBridgeSnapshot, mission_bridge_telemetry
from orion.mission_readiness import ReadinessLevel, assess_mission_readiness, require_current_mission_data


@pytest.fixture(autouse=True)
def reset_bridge() -> None:
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    yield
    mission_bridge_telemetry.disconnect(clear_indexes=True)


def test_readiness_is_not_ready_without_telemetry() -> None:
    readiness = assess_mission_readiness()

    assert readiness.level is ReadinessLevel.NOT_READY
    assert readiness.mission_data_current is False


def test_readiness_becomes_degraded_with_live_empty_snapshot() -> None:
    mission_bridge_telemetry.ingest(
        MissionBridgeSnapshot(
            session_id="mission-1",
            mission_name="Test Mission",
            player_callsign="Ford 1-1",
            sequence=1,
            generated_at=datetime.now(UTC),
            units=[],
            landmarks=[],
        )
    )

    readiness = assess_mission_readiness()

    assert readiness.level is ReadinessLevel.DEGRADED
    assert readiness.mission_data_current is True
    assert any(check.check_id == "coalition_units" and not check.ok for check in readiness.checks)


def test_require_current_mission_data_rejects_disconnected_bridge() -> None:
    with pytest.raises(RuntimeError, match="unavailable or stale"):
        require_current_mission_data()
