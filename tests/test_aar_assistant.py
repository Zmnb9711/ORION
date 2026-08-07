from __future__ import annotations

import orion.voice_mission_context_queries as mission_voice
from orion.coalition_radio import CoalitionRadioUnit, RadioModulation, coalition_radio
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset, build_live_mission_context
from orion.mission_store import mission_store
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand
from orion.voice_execution import ExecutionState, voice_execution


def _aar_context() -> LiveMissionContext:
    return LiveMissionContext(
        available=True,
        mission_id="aar-test",
        ownship=OwnshipContext(aircraft_type="FA-18C_hornet", latitude=41.0, longitude=41.0, altitude_m=5000, heading_deg=90, true_airspeed_mps=220),
        tankers=[SupportAsset(
            unit_id="tanker-1",
            callsign="Texaco",
            role=DcsRecipientType.TANKER,
            unit_type="KC-135",
            frequency_mhz=251.5,
            modulation="AM",
            tacan_channel=31,
            tacan_band="Y",
            aar_available=True,
            latitude=41.0,
            longitude=41.3,
            altitude_m=7500,
            heading_deg=270,
            speed_mps=180,
            distance_km=25.2,
            bearing_deg=90,
            position_source="mission_snapshot",
        )],
    )


def test_support_asset_enriches_tanker_navigation_data() -> None:
    mission_store.replace(MissionSnapshot(
        mission_id="aar-live",
        units=[MissionUnit(
            unit_id="tanker-1",
            name="Texaco 1-1",
            coalition=Coalition.BLUE,
            category=UnitCategory.AIRCRAFT,
            type_name="KC-135",
            position=MissionPosition(latitude=41.0, longitude=41.3, altitude_m=7500),
            heading_deg=270,
            speed_mps=180,
        )],
    ))
    coalition_radio.replace([CoalitionRadioUnit(
        unit_id="tanker-1",
        callsign="Texaco",
        recipient_type=DcsRecipientType.TANKER,
        unit_type="KC-135",
        coalition="blue",
        frequency_mhz=251.5,
        modulation=RadioModulation.AM,
        tacan_channel=31,
        tacan_band="Y",
        aar_available=True,
    )])
    try:
        context = build_live_mission_context()
        tanker = context.tankers[0]
        assert tanker.tacan_channel == 31
        assert tanker.tacan_band == "Y"
        assert tanker.aar_available is True
        assert tanker.heading_deg == 270
        assert tanker.speed_mps == 180
    finally:
        mission_store._snapshot = None
        coalition_radio.replace([])


def test_tanker_brief_contains_live_aar_data(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", _aar_context)
    result = mission_voice.execute_mission_context_query("nearest_tanker", "Где ближайший танкер?")
    assert result.completed is True
    assert "Texaco" in result.spoken_text
    assert "TACAN 31 Y" in result.spoken_text
    assert "251.500" in result.spoken_text
    assert "Курс 270" in result.spoken_text
    assert "Дозаправка доступна" in result.spoken_text


def test_tacan_query_uses_live_mission_context(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", _aar_context)
    command = VoiceCommand(transcript="TACAN танкера", intent="request_tacan", agent=VoiceAgent.TANKER, priority=CommandPriority.HIGH)
    outcome = voice_execution.execute(command)
    assert outcome.state == ExecutionState.COMPLETED
    assert outcome.adapter == "live-mission-context"
    assert "31 Y" in outcome.message


def test_frequency_query_uses_live_mission_context(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", _aar_context)
    command = VoiceCommand(transcript="Частота танкера", intent="request_frequency", agent=VoiceAgent.TANKER, priority=CommandPriority.HIGH)
    outcome = voice_execution.execute(command)
    assert outcome.state == ExecutionState.COMPLETED
    assert "251.500" in outcome.message


def test_unavailable_aar_tanker_is_not_selected(monkeypatch) -> None:
    context = _aar_context()
    context.tankers[0].aar_available = False
    monkeypatch.setattr(mission_voice, "build_live_mission_context", lambda: context)
    result = mission_voice.execute_mission_context_query("nearest_tanker", "Где ближайший танкер?")
    assert result.completed is False
    assert "не найден" in result.spoken_text
