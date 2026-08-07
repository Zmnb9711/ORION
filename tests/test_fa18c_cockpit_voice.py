from orion.fa18c_cockpit import HornetCockpitControlId, fa18c_cockpit
from orion.voice_context import VoiceConversationContext
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand
from orion.voice_knowledge_queries import execute_aircraft_knowledge_query
from orion.voice_understanding import parse_transcript


def test_hornet_cockpit_lookup_finds_ufc_and_comm_presets() -> None:
    ufc = fa18c_cockpit.find("где UFC")
    comm = fa18c_cockpit.find("COMM1 preset")

    assert ufc and ufc[0].control_id is HornetCockpitControlId.UFC
    assert comm and comm[0].control_id is HornetCockpitControlId.COMM1_CHANNEL
    assert "mission_radio_presets" in comm[0].live_data_preferred


def test_voice_parser_routes_hornet_cockpit_question_to_akl() -> None:
    context = VoiceConversationContext(session_id="hornet", entities={"aircraft_id": "fa-18c"})

    parsed = parse_transcript("Где UFC?", context)

    assert len(parsed.commands) == 1
    assert parsed.commands[0].intent == "aircraft_knowledge_query"
    assert parsed.commands[0].agent is VoiceAgent.FLIGHT_ADVISOR
    assert parsed.commands[0].context["context_aircraft_id"] == "fa-18c"


def test_voice_knowledge_returns_structured_hornet_cockpit_answer_without_network() -> None:
    command = VoiceCommand(
        transcript="Где UFC?",
        intent="aircraft_knowledge_query",
        agent=VoiceAgent.FLIGHT_ADVISOR,
        priority=CommandPriority.NORMAL,
        context={"context_aircraft_id": "fa-18c"},
    )

    result = execute_aircraft_knowledge_query(command)

    assert result.completed is True
    assert result.data["knowledge_layer"] == "structured_hornet_cockpit"
    assert result.data["network_required"] is False
    assert "UFC" in result.spoken_text


def test_voice_knowledge_returns_structured_hornet_procedure() -> None:
    command = VoiceCommand(
        transcript="Как настроить TACAN?",
        intent="aircraft_knowledge_query",
        agent=VoiceAgent.FLIGHT_ADVISOR,
        priority=CommandPriority.NORMAL,
        context={"context_aircraft_id": "fa-18c"},
    )

    result = execute_aircraft_knowledge_query(command)

    assert result.completed is True
    assert result.data["knowledge_layer"] in {"structured_hornet_procedure", "structured_hornet_system"}
    assert result.data["network_required"] is False
