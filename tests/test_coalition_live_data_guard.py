from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from orion.coalition_control_api import _require_live_mission_data
from orion.mission_bridge_ingest import MissionBridgeSnapshot, mission_bridge_telemetry


@pytest.fixture(autouse=True)
def reset_bridge() -> None:
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    yield
    mission_bridge_telemetry.disconnect(clear_indexes=True)


def test_guard_rejects_lookup_without_current_mission_data() -> None:
    with pytest.raises(HTTPException) as error:
        _require_live_mission_data()

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "mission_data_unavailable"
    assert error.value.detail["readiness"]["level"] == "not_ready"


def test_guard_allows_lookup_with_current_mission_data() -> None:
    mission_bridge_telemetry.ingest(
        MissionBridgeSnapshot(
            session_id="mission-live",
            mission_name="Live Mission",
            player_callsign="Ford 1-1",
            sequence=1,
            generated_at=datetime.now(UTC),
            units=[],
            landmarks=[],
        )
    )

    _require_live_mission_data()
