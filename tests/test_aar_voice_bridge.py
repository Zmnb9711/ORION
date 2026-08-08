from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orion.aar_proactive import AarProactiveUpdate
from orion.aar_rendezvous import AarPhase
from orion.aar_runtime_monitor import AarRuntimeMonitorResult
from orion.aar_voice_bridge import AarVoiceBridge, aar_voice_bridge
from orion.app import app
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommandQueue, voice_commands


class StubMonitor:
    def __init__(self, result: AarRuntimeMonitorResult) -> None:
        self.result = result

    def poll(self, language: str = "en") -> AarRuntimeMonitorResult:
        return self.result


@pytest.fixture(autouse=True)
def reset_global_voice_queue() -> None:
    voice_commands._commands.clear()
    yield
    voice_commands._commands.clear()


def _result(*, announce: bool, reason: str | None = None, text: str = "") -> AarRuntimeMonitorResult:
    return AarRuntimeMonitorResult(
        active_tanker_present=reason != "active_tanker_lost",
        update=AarProactiveUpdate(
            should_announce=announce,
            spoken_text=text,
            reason=reason,
            phase=AarPhase.RENDEZVOUS,
        ),
    )


def test_silent_monitor_update_does_not_enqueue_voice_command() -> None:
    queue = VoiceCommandQueue()
    bridge = AarVoiceBridge(StubMonitor(_result(announce=False)), queue)

    result = bridge.poll_and_enqueue("en")

    assert result.enqueued is None
    assert queue.list() == []


def test_tanker_loss_is_enqueued_as_high_priority_tanker_voice() -> None:
    queue = VoiceCommandQueue()
    bridge = AarVoiceBridge(
        StubMonitor(_result(
            announce=True,
            reason="active_tanker_lost",
            text="Active tanker lost from the mission picture.",
        )),
        queue,
    )

    result = bridge.poll_and_enqueue("en")

    assert result.enqueued is not None
    assert result.enqueued.agent is VoiceAgent.TANKER
    assert result.enqueued.priority is CommandPriority.HIGH
    assert result.enqueued.intent == "aar_proactive:active_tanker_lost"
    assert result.enqueued.context["aar_phase"] == "rendezvous"
    assert result.enqueued.context["active_tanker_present"] is False


def test_normal_aar_callout_uses_normal_priority() -> None:
    queue = VoiceCommandQueue()
    bridge = AarVoiceBridge(
        StubMonitor(_result(
            announce=True,
            reason="precontact_ready",
            text="Texaco, join-up stabilized. Ready to request pre-contact.",
        )),
        queue,
    )

    result = bridge.poll_and_enqueue("en")

    assert result.enqueued is not None
    assert result.enqueued.priority is CommandPriority.NORMAL
    assert queue.start_next().command_id == result.enqueued.command_id


def test_proactive_voice_api_publishes_into_shared_voice_queue(monkeypatch) -> None:
    monitor_result = _result(
        announce=True,
        reason="contact_envelope_lost",
        text="Outside contact envelope: closure. Correct parameters before contact.",
    )
    monkeypatch.setattr(aar_voice_bridge._monitor, "poll", lambda language="en": monitor_result)

    with TestClient(app) as client:
        response = client.post("/v1/aar/proactive/voice", params={"language": "en"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["enqueued"] is not None
    assert payload["enqueued"]["priority"] == 30
    queued = voice_commands.list()
    assert len(queued) == 1
    assert queued[0].intent == "aar_proactive:contact_envelope_lost"
