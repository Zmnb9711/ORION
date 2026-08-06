from fastapi.testclient import TestClient

from orion.app import app
from orion.coalition_radio import (
    CallsignLookupQuery,
    CoalitionRadioDirectory,
    CoalitionRadioUnit,
)
from orion.dcs_capabilities import DcsRecipientType
from orion.voice_core import VoiceAgent
from orion.voice_understanding import parse_transcript


def test_callsigns_can_be_listed_by_unit_type() -> None:
    directory = CoalitionRadioDirectory()
    directory.replace(
        [
            CoalitionRadioUnit(
                unit_id="tanker-1",
                callsign="Texaco 1-1",
                recipient_type=DcsRecipientType.TANKER,
                coalition="blue",
                frequency_mhz=251.0,
            ),
            CoalitionRadioUnit(
                unit_id="awacs-1",
                callsign="Overlord 1-1",
                recipient_type=DcsRecipientType.AWACS,
                coalition="blue",
                frequency_mhz=251.5,
            ),
        ]
    )

    result = directory.lookup_callsigns(
        CallsignLookupQuery(coalition="blue", recipient_type=DcsRecipientType.TANKER)
    )

    assert result.found is True
    assert [unit.callsign for unit in result.units] == ["Texaco 1-1"]


def test_callsign_lookup_does_not_invent_missing_units() -> None:
    result = CoalitionRadioDirectory().lookup_callsigns(CallsignLookupQuery(text="Magic"))
    assert result.found is False
    assert result.units == []


def test_voice_parser_recognizes_callsign_request() -> None:
    parsed = parse_transcript("Какие позывные у танкеров?")
    assert parsed.commands[0].intent == "find_unit_callsign"
    assert parsed.commands[0].agent is VoiceAgent.COALITION_AIRCRAFT


def test_callsign_route_is_available() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/v1/coalition-control/callsigns/lookup" in paths
