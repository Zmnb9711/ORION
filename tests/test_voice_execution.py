from fastapi.testclient import TestClient

from orion.app import app
from orion.voice_core import VoiceAgent, VoiceCommand, VoiceCommandCreate, VoiceCommandQueue
from orion.voice_execution import ExecutionState, VoiceExecutionDispatcher


def test_tanker_command_requires_bridge_adapter() -> None:
    dispatcher = VoiceExecutionDispatcher()
    command = VoiceCommand(
        transcript="Найди ближайший танкер",
        intent="find_tanker",
        agent=VoiceAgent.TANKER,
        priority=30,
    )

    outcome = dispatcher.execute(command)

    assert outcome.state is ExecutionState.BRIDGE_REQUIRED
    assert outcome.adapter == "tanker-service"
    assert outcome.payload["command_id"] == str(command.command_id)


def test_conversation_command_routes_to_dialogue_engine() -> None:
    dispatcher = VoiceExecutionDispatcher()
    command = VoiceCommand(
        transcript="Как дела?",
        intent="general_conversation",
        agent=VoiceAgent.GENERAL_CONVERSATION,
        priority=10,
    )

    outcome = dispatcher.execute(command)

    assert outcome.state is ExecutionState.ACCEPTED
    assert outcome.adapter == "ai-dialogue"


def test_execute_next_starts_highest_priority_command() -> None:
    queue = VoiceCommandQueue()
    queue.submit(
        VoiceCommandCreate(
            transcript="chat",
            intent="general_conversation",
            agent=VoiceAgent.GENERAL_CONVERSATION,
        )
    )
    urgent = queue.submit(
        VoiceCommandCreate(
            transcript="request picture",
            intent="request_picture",
            agent=VoiceAgent.AWACS,
            priority=30,
        )
    )

    started = queue.start_next()

    assert started is not None
    assert started.command_id == urgent.command_id


def test_execution_routes_are_available() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]

    assert "/v1/voice-commands/executors" in paths
    assert "/v1/voice-commands/execute-next" in paths
