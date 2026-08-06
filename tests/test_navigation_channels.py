from datetime import UTC, datetime

import pytest

from orion.mission_bridge_ingest import MissionBridgeSnapshot, mission_bridge_telemetry
from orion.navigation_channels import (
    NavigationChannelOwnerType,
    NavigationChannelQuery,
    NavigationChannelSystem,
    NavigationPresetChannel,
    navigation_channels,
)
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand
from orion.voice_execution import ExecutionState, voice_execution
from orion.voice_understanding import parse_transcript


@pytest.fixture(autouse=True)
def reset_state() -> None:
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    navigation_channels.replace([])
    yield
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    navigation_channels.replace([])


def _load_live_mission() -> None:
    mission_bridge_telemetry.ingest(
        MissionBridgeSnapshot(
            session_id="channels-1",
            mission_name="Channel Test",
            sequence=1,
            generated_at=datetime.now(UTC),
        )
    )


def test_directory_finds_airfield_rsbn_channel() -> None:
    navigation_channels.replace([
        NavigationPresetChannel(
            preset_id="damascus-rsbn",
            system=NavigationChannelSystem.RSBN,
            owner_type=NavigationChannelOwnerType.AIRFIELD,
            owner_id="damascus",
            owner_name="Damascus",
            channel="22",
            purpose="navigation",
        )
    ])

    result = navigation_channels.lookup(
        NavigationChannelQuery(text="Damascus", system=NavigationChannelSystem.RSBN)
    )

    assert result.found is True
    assert result.channels[0].channel == "22"


def test_voice_parser_recognizes_adf_channel_request() -> None:
    parsed = parse_transcript("Дай канал АРК для Алеппо")

    assert parsed.commands[0].intent == "find_adf_channel"
    assert parsed.commands[0].agent is VoiceAgent.NAVIGATION


def test_voice_query_returns_radio_preset_for_unit() -> None:
    _load_live_mission()
    navigation_channels.replace([
        NavigationPresetChannel(
            preset_id="colt-radio-3",
            system=NavigationChannelSystem.RADIO,
            owner_type=NavigationChannelOwnerType.UNIT,
            owner_id="colt-1",
            owner_name="Colt 1",
            channel="3",
            frequency_mhz=127.5,
            modulation="AM",
            purpose="flight",
        )
    ])
    command = VoiceCommand(
        transcript="Дай предустановленный канал Colt 1",
        intent="find_radio_preset_channel",
        agent=VoiceAgent.NAVIGATION,
        priority=CommandPriority.NORMAL,
    )

    outcome = voice_execution.execute(command)

    assert outcome.state is ExecutionState.COMPLETED
    assert "channel 3" in outcome.message
    assert "127.500" in outcome.message


def test_missing_channel_is_not_invented() -> None:
    _load_live_mission()
    command = VoiceCommand(
        transcript="Дай канал РСБН для Алеппо",
        intent="find_rsbn_channel",
        agent=VoiceAgent.NAVIGATION,
        priority=CommandPriority.NORMAL,
    )

    outcome = voice_execution.execute(command)

    assert outcome.state is ExecutionState.REJECTED
    assert outcome.payload["reason"] == "preset_channel_not_found"
