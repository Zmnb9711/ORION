from fastapi.testclient import TestClient

from orion.app import app
from orion.voice_core import (
    CommandPriority,
    CommandState,
    VoiceAgent,
    VoiceCommandCreate,
    VoiceCommandQueue,
)


def test_voice_queue_runs_highest_priority_first() -> None:
    queue = VoiceCommandQueue()
    queue.submit(VoiceCommandCreate(transcript="chat", intent="talk", agent=VoiceAgent.GENERAL_CONVERSATION))
    urgent = queue.submit(
        VoiceCommandCreate(
            transcript="missile",
            intent="missile_warning",
            agent=VoiceAgent.THREAT_ANALYZER,
            priority=CommandPriority.CRITICAL,
        )
    )

    started = queue.start_next()
    assert started is not None
    assert started.command_id == urgent.command_id
    assert started.state is CommandState.RUNNING


def test_critical_command_preempts_running_lower_priority() -> None:
    queue = VoiceCommandQueue()
    normal = queue.submit(
        VoiceCommandCreate(transcript="nearest tanker", intent="find_tanker", agent=VoiceAgent.TANKER)
    )
    queue.start_next()
    queue.submit(
        VoiceCommandCreate(
            transcript="terrain",
            intent="terrain_warning",
            agent=VoiceAgent.THREAT_ANALYZER,
            priority=CommandPriority.CRITICAL,
        )
    )

    interrupted = queue.get(normal.command_id)
    assert interrupted is not None
    assert interrupted.state is CommandState.CANCELLED


def test_voice_core_routes_are_available() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/voice-commands" in paths
    assert "/v1/voice-commands/next" in paths
    assert "/v1/voice-commands/{command_id}/cancel" in paths
