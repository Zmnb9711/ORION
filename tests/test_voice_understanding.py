from fastapi.testclient import TestClient

from orion.app import app
from orion.voice_core import CommandPriority, VoiceAgent
from orion.voice_understanding import parse_transcript


def test_russian_tanker_request_is_routed() -> None:
    parsed = parse_transcript("Найди ближайший танкер")
    command = parsed.commands[0]
    assert command.agent is VoiceAgent.TANKER
    assert command.intent == "find_tanker"
    assert command.priority is CommandPriority.HIGH


def test_english_awacs_request_is_routed() -> None:
    parsed = parse_transcript("Request picture from AWACS")
    command = parsed.commands[0]
    assert command.agent is VoiceAgent.AWACS
    assert command.intent == "request_picture"


def test_compound_transcript_creates_multiple_commands() -> None:
    parsed = parse_transcript("Найди танкер, затем запроси picture у AWACS")
    assert len(parsed.commands) == 2
    assert parsed.commands[0].agent is VoiceAgent.TANKER
    assert parsed.commands[1].agent is VoiceAgent.AWACS


def test_critical_warning_has_critical_priority() -> None:
    parsed = parse_transcript("Missile!")
    assert parsed.commands[0].priority is CommandPriority.CRITICAL
    assert parsed.commands[0].agent is VoiceAgent.THREAT_ANALYZER


def test_unknown_phrase_falls_back_to_conversation() -> None:
    parsed = parse_transcript("Как сегодня погода?")
    assert parsed.commands[0].agent is VoiceAgent.GENERAL_CONVERSATION
    assert parsed.commands[0].priority is CommandPriority.LOW


def test_understanding_routes_are_available() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/voice-commands/understand" in paths
    assert "/v1/voice-commands/submit-transcript" in paths
