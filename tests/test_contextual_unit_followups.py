from datetime import UTC, datetime

import pytest

from orion.coalition_radio import CoalitionRadioUnit, MissionPoint, RadioModulation
from orion.dcs_capabilities import DcsRecipientType
from orion.mission_bridge_ingest import MissionBridgeSnapshot, mission_bridge_telemetry
from orion.voice_context import voice_contexts
from orion.voice_pipeline import process_transcript


@pytest.fixture(autouse=True)
def reset_state() -> None:
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    voice_contexts.clear("dialogue-1")
    yield
    mission_bridge_telemetry.disconnect(clear_indexes=True)
    voice_contexts.clear("dialogue-1")


def _load_mission() -> None:
    mission_bridge_telemetry.ingest(
        MissionBridgeSnapshot(
            session_id="syria-dialogue",
            mission_name="Syria Dialogue",
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
                    point=MissionPoint(x_m=12_500, z_m=8_000),
                )
            ],
            landmarks=[],
        )
    )


def test_frequency_follow_up_uses_previous_unit_context() -> None:
    _load_mission()
    first = process_transcript("Назови позывной Colt 1", "dialogue-1")

    assert first.context.active_subject == "Colt 1"
    assert first.context.entities["unit_id"] == "colt-1"

    second = process_transcript("Какая у него частота?", "dialogue-1")

    assert second.parsed.commands[0].intent == "find_unit_frequency"
    assert "127.500" in (second.executions[0].spoken_text or "")


def test_position_follow_up_reports_live_coordinates() -> None:
    _load_mission()
    process_transcript("Назови позывной Colt 1", "dialogue-1")

    result = process_transcript("Где он сейчас?", "dialogue-1")

    assert result.parsed.commands[0].intent == "find_unit_position"
    assert result.executions[0].outcome.payload["coordinates"] == {"x_m": 12500.0, "z_m": 8000.0}


def test_map_follow_up_returns_map_action() -> None:
    _load_mission()
    process_transcript("Назови позывной Colt 1", "dialogue-1")

    result = process_transcript("Покажи его на карте", "dialogue-1")

    assert result.parsed.commands[0].intent == "show_unit_on_map"
    assert result.executions[0].outcome.payload["action"] == "show_unit_on_map"
    assert "Показываю Colt 1" in (result.executions[0].spoken_text or "")
