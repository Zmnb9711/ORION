from datetime import UTC, datetime

import pytest

from orion.mission_bridge_ingest import (
    MissionBridgeDelta,
    MissionBridgeSnapshot,
    mission_bridge_telemetry,
)
from orion.navigation_channels import (
    NavigationChannelOwnerType,
    NavigationChannelSystem,
    NavigationPresetChannel,
    navigation_channels,
)


@pytest.fixture(autouse=True)
def reset_bridge() -> None:
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    yield
    mission_bridge_telemetry.disconnect(clear_indexes=True)


def _channel(preset_id: str, channel: str) -> NavigationPresetChannel:
    return NavigationPresetChannel(
        preset_id=preset_id,
        system=NavigationChannelSystem.RSBN,
        owner_type=NavigationChannelOwnerType.AIRFIELD,
        owner_id="damascus",
        owner_name="Damascus",
        channel=channel,
        purpose="navigation",
        aircraft_type="MiG-21bis",
    )


def test_snapshot_replaces_preset_channel_index() -> None:
    result = mission_bridge_telemetry.ingest(
        MissionBridgeSnapshot(
            session_id="mission-1",
            mission_name="Syria",
            sequence=1,
            generated_at=datetime.now(UTC),
            preset_channels=[_channel("rsbn-damascus", "22")],
        )
    )

    assert result.accepted is True
    assert result.state.preset_channel_count == 1
    assert navigation_channels.list()[0].channel == "22"


def test_delta_updates_and_removes_preset_channels() -> None:
    mission_bridge_telemetry.ingest(
        MissionBridgeSnapshot(
            session_id="mission-1",
            sequence=1,
            generated_at=datetime.now(UTC),
            preset_channels=[_channel("rsbn-damascus", "22")],
        )
    )

    updated = mission_bridge_telemetry.apply_delta(
        MissionBridgeDelta(
            session_id="mission-1",
            sequence=2,
            generated_at=datetime.now(UTC),
            upsert_preset_channels=[_channel("rsbn-damascus", "23")],
        )
    )
    assert updated.accepted is True
    assert navigation_channels.list()[0].channel == "23"

    removed = mission_bridge_telemetry.apply_delta(
        MissionBridgeDelta(
            session_id="mission-1",
            sequence=3,
            generated_at=datetime.now(UTC),
            remove_preset_ids=["rsbn-damascus"],
        )
    )
    assert removed.accepted is True
    assert removed.state.preset_channel_count == 0
    assert navigation_channels.list() == []


def test_disconnect_clears_preset_channels() -> None:
    mission_bridge_telemetry.ingest(
        MissionBridgeSnapshot(
            session_id="mission-1",
            sequence=1,
            generated_at=datetime.now(UTC),
            preset_channels=[_channel("rsbn-damascus", "22")],
        )
    )

    mission_bridge_telemetry.disconnect(clear_indexes=True)

    assert navigation_channels.list() == []
