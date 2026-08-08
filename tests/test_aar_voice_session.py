from __future__ import annotations

import pytest

import orion.aar_rendezvous as aar_module
from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset
from orion.voice_core import VoiceCommand
from orion.voice_execution import ExecutionState, voice_execution
from orion.voice_understanding import parse_transcript


@pytest.fixture(autouse=True)
def reset_aar() -> None:
    aar_rendezvous.reset()
    yield
    aar_rendezvous.reset()


def _context() -> LiveMissionContext:
    return LiveMissionContext(
        available=True,
        ownship=OwnshipContext(
            aircraft_type="FA-18C_hornet",
            latitude=41.0,
            longitude=41.0,
            altitude_m=5000,
            heading_deg=90,
            true_airspeed_mps=250,
        ),
        tankers=[SupportAsset(
            unit_id="tanker-1",
            callsign="Texaco",
            role=DcsRecipientType.TANKER,
            coalition=Coalition.BLUE,
            available=True,
            aar_available=True,
            latitude=41.0,
            longitude=41.2,
            altitude_m=7000,
            distance_km=18.52,
            bearing_deg=90,
            heading_deg=0,
            speed_mps=150,
            frequency_mhz=251.5,
            modulation="AM",
            tacan_channel=31,
            tacan_band="Y",
        )],
    )


def test_parser_routes_russian_and_english_aar_commands() -> None:
    assert parse_transcript("Начать дозаправку").commands[0].intent == "aar_start"
    assert parse_transcript("Статус сближения").commands[0].intent == "aar_status"
    assert parse_transcript("Pre-contact").commands[0].intent == "aar_pre_contact"
    assert parse_transcript("Contact with tanker").commands[0].intent == "aar_contact"
    assert parse_transcript("Refueling complete").commands[0].intent == "aar_complete"
    assert parse_transcript("Abort AAR").commands[0].intent == "aar_abort"


def test_aar_contact_does_not_capture_awacs_contact() -> None:
    command = parse_transcript("Contact AWACS").commands[0]
    assert command.intent == "contact_awacs"


def test_voice_execution_starts_and_tracks_aar_session(monkeypatch) -> None:
    monkeypatch.setattr(aar_module, "build_live_mission_context", _context)
    create = parse_transcript("Начать дозаправку").commands[0]
    outcome = voice_execution.execute(VoiceCommand(**create.model_dump()))
    assert outcome.state == ExecutionState.COMPLETED
    assert outcome.adapter == "aar-rendezvous"
    assert outcome.payload["aar_session"]["phase"] == AarPhase.RENDEZVOUS.value
    assert outcome.payload["intercept_guidance"] is not None
    assert "Texaco" in outcome.message
    assert "TACAN 31 Y" in outcome.message


def test_voice_status_uses_active_tanker_and_dynamic_guidance(monkeypatch) -> None:
    monkeypatch.setattr(aar_module, "build_live_mission_context", _context)
    start = parse_transcript("Start AAR").commands[0]
    voice_execution.execute(VoiceCommand(**start.model_dump()))
    status = parse_transcript("Rendezvous status").commands[0]
    outcome = voice_execution.execute(VoiceCommand(**status.model_dump()))
    assert outcome.state == ExecutionState.COMPLETED
    assert outcome.payload["aar_session"]["tanker_callsign"] == "Texaco"
    assert outcome.payload["intercept_guidance"] is not None


def test_aar_voice_commands_do_not_fall_through_to_bridge(monkeypatch) -> None:
    monkeypatch.setattr(aar_module, "build_live_mission_context", _context)
    start = parse_transcript("Начать дозаправку").commands[0]
    outcome = voice_execution.execute(VoiceCommand(**start.model_dump()))
    assert outcome.state != ExecutionState.BRIDGE_REQUIRED
