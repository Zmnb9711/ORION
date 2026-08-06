from orion.knowledge_manager import DocumentSection, OfficialDocument, knowledge_manager
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand
from orion.voice_execution import ExecutionState, voice_execution
from orion.voice_understanding import parse_transcript


def _seed_hornet_manual(*, cached: bool) -> None:
    knowledge_manager.register(
        OfficialDocument(
            document_id="voice-fa18c-manual",
            aircraft_id="fa-18c",
            title="F/A-18C Hornet Flight Manual",
            url="https://www.digitalcombatsimulator.com/en/downloads/documentation/",
        )
    )
    knowledge_manager.replace_sections(
        "voice-fa18c-manual",
        [
            DocumentSection(
                section_id="voice-fa18c-stored-heading",
                document_id="voice-fa18c-manual",
                title="Stored Heading Alignment",
                summary="Use the stored heading option when the required preconditions are satisfied.",
                page_start=287,
                keywords={"stored", "heading", "alignment", "ins"},
                cached=cached,
            )
        ],
    )


def test_manual_question_is_recognized() -> None:
    parsed = parse_transcript("Как выполнить stored heading alignment на F/A-18C?")
    command = parsed.commands[0]
    assert command.intent == "aircraft_knowledge_query"
    assert command.agent is VoiceAgent.FLIGHT_ADVISOR
    assert command.context["parser"] == "rules-v8"


def test_voice_query_returns_official_source_and_page() -> None:
    _seed_hornet_manual(cached=True)
    command = VoiceCommand(
        transcript="Как выполнить stored heading alignment на F/A-18C?",
        intent="aircraft_knowledge_query",
        agent=VoiceAgent.FLIGHT_ADVISOR,
        priority=CommandPriority.NORMAL,
    )
    outcome = voice_execution.execute(command)
    assert outcome.state is ExecutionState.COMPLETED
    assert outcome.adapter == "official-knowledge"
    assert outcome.payload["knowledge_layer"] == "official"
    assert outcome.payload["network_required"] is False
    assert outcome.payload["section"]["page_start"] == 287
    assert "официальному руководству" in outcome.payload["spoken_text"]


def test_uncached_manual_section_requests_network_data() -> None:
    _seed_hornet_manual(cached=False)
    command = VoiceCommand(
        transcript="Согласно руководству F/A-18C, как выполнить stored heading alignment?",
        intent="aircraft_knowledge_query",
        agent=VoiceAgent.FLIGHT_ADVISOR,
        priority=CommandPriority.NORMAL,
    )
    outcome = voice_execution.execute(command)
    assert outcome.state is ExecutionState.COMPLETED
    assert outcome.payload["network_required"] is True
    assert "сайта DCS World" in outcome.payload["spoken_text"]


def test_aircraft_must_be_resolved() -> None:
    command = VoiceCommand(
        transcript="Как выполнить выравнивание?",
        intent="aircraft_knowledge_query",
        agent=VoiceAgent.FLIGHT_ADVISOR,
        priority=CommandPriority.NORMAL,
    )
    outcome = voice_execution.execute(command)
    assert outcome.state is ExecutionState.REJECTED
    assert outcome.payload["reason"] == "aircraft_not_resolved"
