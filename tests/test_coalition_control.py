from orion.coalition_radio import (
    CoalitionRadioDirectory,
    CoalitionRadioUnit,
    RadioLookupQuery,
    RadioModulation,
)
from orion.dcs_capabilities import DcsRecipientType
from orion.dcs_command_translation import SemanticCommandRequest, build_command_plan
from orion.voice_core import VoiceAgent
from orion.voice_understanding import parse_transcript


def test_native_wingman_command_is_executable() -> None:
    plan = build_command_plan(
        SemanticCommandRequest(
            transcript="Второй, прикрой меня",
            recipient_type=DcsRecipientType.WINGMAN,
            intent="cover_me",
        )
    )
    assert plan.executable is True
    assert plan.decision.dcs_command == "Cover Me"
    assert plan.requires_confirmation is False


def test_mission_bridge_command_requires_bridge() -> None:
    plan = build_command_plan(
        SemanticCommandRequest(
            transcript="Alpha, атакуйте колонну",
            recipient_type=DcsRecipientType.COALITION_GROUND,
            recipient_id="Alpha",
            intent="attack_group",
            target_available=True,
        )
    )
    assert plan.executable is False
    assert "Mission Bridge" in plan.decision.reason


def test_mission_bridge_command_requires_confirmation_when_available() -> None:
    plan = build_command_plan(
        SemanticCommandRequest(
            transcript="Alpha, атакуйте колонну",
            recipient_type=DcsRecipientType.COALITION_GROUND,
            recipient_id="Alpha",
            intent="attack_group",
            mission_bridge_available=True,
            target_available=True,
        )
    )
    assert plan.executable is True
    assert plan.requires_confirmation is True
    assert plan.confirmation_prompt is not None


def test_radio_lookup_returns_frequency_and_modulation() -> None:
    directory = CoalitionRadioDirectory()
    directory.upsert(
        CoalitionRadioUnit(
            unit_id="pontiac-2",
            callsign="Pontiac 2",
            recipient_type=DcsRecipientType.COALITION_AIRCRAFT,
            coalition="blue",
            frequency_mhz=127.5,
            modulation=RadioModulation.AM,
        )
    )
    result = directory.lookup(RadioLookupQuery(text="Pontiac", coalition="blue"))
    assert result.found is True
    assert result.unit is not None
    assert result.unit.frequency_mhz == 127.5
    assert "AM" in result.message


def test_radio_lookup_does_not_invent_missing_frequency() -> None:
    directory = CoalitionRadioDirectory()
    directory.upsert(
        CoalitionRadioUnit(
            unit_id="alpha",
            callsign="Alpha",
            recipient_type=DcsRecipientType.COALITION_GROUND,
            coalition="blue",
        )
    )
    result = directory.lookup(RadioLookupQuery(text="Alpha"))
    assert result.found is True
    assert result.unit is not None
    assert result.unit.frequency_mhz is None
    assert "no radio frequency" in result.message


def test_voice_parser_recognizes_wingman_and_flight() -> None:
    wingman = parse_transcript("Второй, прикрой меня").commands[0]
    flight = parse_transcript("Звено, атакуйте воздушные цели").commands[0]
    assert wingman.agent is VoiceAgent.WINGMAN
    assert wingman.intent == "command_wingman"
    assert flight.agent is VoiceAgent.FLIGHT
    assert flight.intent == "command_flight"
