from fastapi.testclient import TestClient

from orion.app import app
from orion.voice_context import VoiceContextStore
from orion.voice_core import VoiceAgent
from orion.voice_understanding import parse_transcript


def test_follow_up_uses_active_tanker_context() -> None:
    store = VoiceContextStore()
    context = store.update(
        "flight-1",
        agent=VoiceAgent.TANKER,
        subject="tanker",
        intent="find_tanker",
    )

    parsed = parse_transcript("Какая у него частота?", context)
    command = parsed.commands[0]
    assert command.agent is VoiceAgent.TANKER
    assert command.intent == "request_frequency"
    assert command.context["active_subject"] == "tanker"


def test_short_tacan_follow_up_uses_active_agent() -> None:
    store = VoiceContextStore()
    context = store.update("flight-2", agent=VoiceAgent.TANKER, subject="tanker")
    command = parse_transcript("А TACAN?", context).commands[0]
    assert command.agent is VoiceAgent.TANKER
    assert command.intent == "request_tacan"


def test_context_api_routes_are_available() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/voice-commands/context/{session_id}" in paths
