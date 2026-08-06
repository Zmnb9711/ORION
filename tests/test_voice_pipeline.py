from datetime import UTC, datetime

import pytest

from orion.coalition_radio import CoalitionRadioUnit, MissionLandmark, MissionPoint, RadioModulation
from orion.dcs_capabilities import DcsRecipientType
from orion.mission_bridge_ingest import MissionBridgeSnapshot, mission_bridge_telemetry
from orion.voice_context import voice_contexts
from orion.voice_core import CommandState
from orion.voice_pipeline import process_transcript


@pytest.fixture(autouse=True)
def reset_state() -> None:
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    voice_contexts.clear("pipeline-test")
    yield
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    voice_contexts.clear("pipeline-test")


def _load_mission() -> None:
    mission_bridge_telemetry.ingest(
        MissionBridgeSnapshot(
            session_id="syria-live",
            mission_name="Syria",
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


def test_pipeline_completes_information_command_and_keeps_spoken_text() -> None:
    _load_mission()

    result = process_transcript("Дай частоту Colt 1", "pipeline-test")

    execution = result.executions[0]
    assert execution.command.state is CommandState.COMPLETED
    assert execution.spoken_text is not None
    assert "127.500" in execution.spoken_text
    assert result.context.entities["last_unit_callsign"] == "Colt 1"
    assert result.context.active_subject == "Colt 1"


def test_pipeline_fails_information_command_when_bridge_is_unavailable() -> None:
    result = process_transcript("Назови позывные", "pipeline-test")

    execution = result.executions[0]
    assert execution.command.state is CommandState.FAILED
    assert execution.spoken_text == "Данные Mission Bridge недоступны или устарели."


def test_pipeline_stores_landmark_context() -> None:
    _load_mission()

    result = process_transcript("Кто у нас рядом с Алеппо в радиусе 20 км", "pipeline-test")

    assert result.executions[0].command.state is CommandState.COMPLETED
    assert result.context.entities["last_landmark"] == "Aleppo"
    assert result.context.active_subject == "Aleppo"
