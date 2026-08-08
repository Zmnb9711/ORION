from __future__ import annotations

import orion.voice_mission_context_queries as mission_voice
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, MissionContact, OwnshipContext, SupportAsset
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand
from orion.voice_execution import ExecutionState, voice_execution
from orion.voice_understanding import parse_transcript


def _context() -> LiveMissionContext:
    return LiveMissionContext(available=True, mission_id="mission-voice", ownship=OwnshipContext(aircraft_type="FA-18C_hornet", latitude=41.0, longitude=41.0, altitude_m=5000), friendlies=[MissionContact(unit_id="blue-1", name="Ford 2-1", coalition=Coalition.BLUE, latitude=41.05, longitude=41.0, altitude_m=5500, distance_km=5.6, bearing_deg=0.0)], hostiles=[MissionContact(unit_id="red-1", name="Bandit 1", coalition=Coalition.RED, latitude=41.0, longitude=41.1, altitude_m=6000, distance_km=8.4, bearing_deg=90.0)], awacs=[SupportAsset(unit_id="awacs-1", callsign="Magic", role=DcsRecipientType.AWACS, frequency_mhz=251.0, modulation="AM")], tankers=[SupportAsset(unit_id="tanker-1", callsign="Texaco", role=DcsRecipientType.TANKER, frequency_mhz=251.5, modulation="AM")], jtac=[SupportAsset(unit_id="jtac-1", callsign="Axeman", role=DcsRecipientType.JTAC, frequency_mhz=133.0, modulation="AM")])


def _located_context() -> LiveMissionContext:
    context = _context()
    context.tankers = [SupportAsset(unit_id="tanker-1", callsign="Texaco", role=DcsRecipientType.TANKER, frequency_mhz=251.5, modulation="AM", latitude=41.0, longitude=41.3, altitude_m=7500, distance_km=25.2, bearing_deg=90.0, position_source="mission_snapshot")]
    return context


def _intercept_context() -> LiveMissionContext:
    context = _located_context()
    context.ownship.heading_deg = 90.0
    context.ownship.true_airspeed_mps = 250.0
    context.tankers[0].heading_deg = 0.0
    context.tankers[0].speed_mps = 150.0
    context.tankers[0].aar_available = True
    return context


def test_parser_routes_specific_context_queries_before_generic_bridge_rules() -> None:
    assert parse_transcript("Какие танкеры доступны?").commands[0].intent == "list_tankers"
    assert parse_transcript("Где ближайший противник?").commands[0].intent == "nearest_hostile"
    assert parse_transcript("Available AWACS").commands[0].intent == "list_awacs"
    assert parse_transcript("Where is the tanker?").commands[0].intent == "nearest_tanker"


def test_nearest_hostile_uses_live_context(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", _context)
    result = mission_voice.execute_mission_context_query("nearest_hostile", "Где ближайший противник?")
    assert result.completed is True and "Bandit 1" in result.spoken_text and "90" in result.spoken_text
    assert result.data["contact"]["distance_km"] == 8.4


def test_support_list_returns_actual_frequency(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", _context)
    result = mission_voice.execute_mission_context_query("list_tankers", "Какие танкеры доступны?")
    assert result.completed is True and "Texaco" in result.spoken_text and "251.500" in result.spoken_text


def test_nearest_tanker_does_not_invent_position(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", _context)
    result = mission_voice.execute_mission_context_query("nearest_tanker", "Где ближайший танкер?")
    assert result.completed is True and result.data["position_available"] is False
    assert result.data["intercept_guidance"] is None
    assert "Положение пока не передано" in result.spoken_text


def test_nearest_tanker_reports_real_range_and_bearing(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", _located_context)
    result = mission_voice.execute_mission_context_query("nearest_tanker", "Где ближайший танкер?")
    assert result.completed is True and result.data["position_available"] is True
    assert "Азимут 90" in result.spoken_text
    assert "13.6 морских миль" in result.spoken_text
    assert "24606 футов" in result.spoken_text
    assert "251.500" in result.spoken_text
    assert result.data["intercept_guidance"] is None


def test_tanker_intercept_guidance_uses_relative_motion(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", _intercept_context)
    result = mission_voice.execute_mission_context_query("find_tanker", "Найди ближайший танкер")
    guidance = result.data["intercept_guidance"]
    assert result.completed is True
    assert guidance is not None and guidance["eta_s"] > 0 and guidance["intercept_distance_km"] > 25
    assert 0 < guidance["intercept_heading_deg"] < 90
    assert "Рекомендуемый курс перехвата" in result.spoken_text
    assert "расчетное время встречи" in result.spoken_text


def test_intercept_guidance_not_invented_when_ownship_speed_missing(monkeypatch) -> None:
    context = _intercept_context(); context.ownship.true_airspeed_mps = None
    monkeypatch.setattr(mission_voice, "build_live_mission_context", lambda: context)
    result = mission_voice.execute_mission_context_query("find_tanker", "Найди танкер")
    assert result.completed is True and result.data["intercept_guidance"] is None
    assert "Рекомендуемый курс перехвата" not in result.spoken_text


def test_execution_dispatches_context_query_without_bridge_requirement(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", _context)
    command = VoiceCommand(transcript="Какие AWACS доступны?", intent="list_awacs", agent=VoiceAgent.AWACS, priority=CommandPriority.NORMAL)
    outcome = voice_execution.execute(command)
    assert outcome.state == ExecutionState.COMPLETED and outcome.adapter == "live-mission-context" and "Magic" in outcome.message


def test_unavailable_mission_context_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(mission_voice, "build_live_mission_context", lambda: LiveMissionContext(available=False, issues=["mission_snapshot_unavailable"]))
    result = mission_voice.execute_mission_context_query("mission_context_summary", "Контекст миссии")
    assert result.completed is False and result.data["issues"] == ["mission_snapshot_unavailable"]
