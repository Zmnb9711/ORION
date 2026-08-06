from datetime import UTC, datetime

import pytest

from orion.coalition_radio import CoalitionRadioUnit, MissionLandmark, MissionPoint, RadioModulation
from orion.dcs_capabilities import DcsRecipientType
from orion.mission_bridge_ingest import MissionBridgeSnapshot, mission_bridge_telemetry
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand
from orion.voice_execution import ExecutionState, voice_execution


@pytest.fixture(autouse=True)
def reset_bridge() -> None:
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    yield
    mission_bridge_telemetry.disconnect(clear_indexes=True)


def _load_mission() -> None:
    mission_bridge_telemetry.ingest(
        MissionBridgeSnapshot(
            session_id="syria-1",
            mission_name="Syria Test",
            player_callsign="Ford 1-1",
            sequence=1,
            generated_at=datetime.now(UTC),
            units=[
                CoalitionRadioUnit(
                    unit_id="colt-1",
                    callsign="Colt 1",
                    recipient_type=DcsRecipientType.COALITION_AIRCRAFT,
                    unit_type="F/A-18C",
                    coalition="blue",
                    frequency_mhz=127.5,
                    modulation=RadioModulation.AM,
                    point=MissionPoint(x_m=10_000, z_m=0),
                )
            ],
            landmarks=[
                MissionLandmark(
                    landmark_id="aleppo",
                    name="Aleppo",
                    aliases=["Алеппо"],
                    point=MissionPoint(x_m=0, z_m=0),
                )
            ],
        )
    )


def _command(intent: str, transcript: str) -> VoiceCommand:
    return VoiceCommand(
        transcript=transcript,
        intent=intent,
        agent=VoiceAgent.COALITION_AIRCRAFT,
        priority=CommandPriority.NORMAL,
    )


def test_voice_frequency_query_returns_spoken_answer() -> None:
    _load_mission()

    outcome = voice_execution.execute(_command("find_unit_frequency", "Дай частоту Colt 1"))

    assert outcome.state is ExecutionState.COMPLETED
    assert outcome.adapter == "mission-information"
    assert "127.500" in outcome.message
    assert "F/A-18C" in outcome.message


def test_voice_near_landmark_query_returns_type_and_distance() -> None:
    _load_mission()

    outcome = voice_execution.execute(
        _command("find_unit_callsigns_near_landmark", "Кто у нас рядом с Алеппо в радиусе 20 км?")
    )

    assert outcome.state is ExecutionState.COMPLETED
    assert "Colt 1" in outcome.message
    assert "F/A-18C" in outcome.message
    assert "10 km" in outcome.message


def test_voice_mission_query_rejects_missing_telemetry() -> None:
    outcome = voice_execution.execute(_command("find_unit_callsign", "Назови позывные"))

    assert outcome.state is ExecutionState.REJECTED
    assert outcome.payload["reason"] == "mission_data_unavailable"
