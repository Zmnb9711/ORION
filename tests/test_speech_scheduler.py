from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from orion.app import app
from orion.speech_scheduler import SpeechDecision, SpeechScheduler, speech_scheduler
from orion.voice_core import CommandPriority, CommandState, VoiceAgent, VoiceCommandCreate, VoiceCommandQueue, voice_commands


def _command(text: str, *, priority: CommandPriority = CommandPriority.NORMAL, agent: VoiceAgent = VoiceAgent.TANKER) -> VoiceCommandCreate:
    return VoiceCommandCreate(transcript=text, intent="announce", agent=agent, priority=priority)


def test_scheduler_selects_highest_priority_queued_voice() -> None:
    queue = VoiceCommandQueue()
    scheduler = SpeechScheduler(queue)
    queue.submit(_command("normal", priority=CommandPriority.NORMAL))
    high = queue.submit(_command("high", priority=CommandPriority.HIGH))

    result = scheduler.select_next()

    assert result.decision is SpeechDecision.READY
    assert result.command is not None
    assert result.command.command_id == high.command_id
    assert result.command.state is CommandState.RUNNING


def test_higher_priority_voice_preempts_current_speech() -> None:
    queue = VoiceCommandQueue()
    scheduler = SpeechScheduler(queue)
    current = queue.submit(_command("routine", priority=CommandPriority.NORMAL))
    queue.start(current.command_id)
    urgent = queue.submit(_command("tanker lost", priority=CommandPriority.HIGH))

    result = scheduler.select_next()

    assert result.decision is SpeechDecision.READY
    assert result.interrupt_current is True
    assert result.interrupted_command_id == str(current.command_id)
    assert queue.get(current.command_id).state is CommandState.CANCELLED
    assert result.command is not None
    assert result.command.command_id == urgent.command_id


def test_equal_priority_waits_while_current_speech_is_running() -> None:
    queue = VoiceCommandQueue()
    scheduler = SpeechScheduler(queue)
    current = queue.submit(_command("first"))
    queue.start(current.command_id)
    queue.submit(_command("second"))

    result = scheduler.select_next()

    assert result.decision is SpeechDecision.BUSY
    assert result.command is not None
    assert result.command.command_id == current.command_id


def test_duplicate_callout_is_suppressed_during_cooldown() -> None:
    queue = VoiceCommandQueue()
    scheduler = SpeechScheduler(queue, duplicate_cooldown_s=10)
    first = queue.submit(_command("closure high"))
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    selected = scheduler.select_next(now)
    assert selected.command is not None
    scheduler.mark_spoken(selected.command, now)
    queue.complete(first.command_id, "spoken")
    queue.submit(_command("closure high"))

    blocked = scheduler.select_next(now + timedelta(seconds=5))
    assert blocked.decision is SpeechDecision.COOLDOWN

    ready = scheduler.select_next(now + timedelta(seconds=11))
    assert ready.decision is SpeechDecision.READY


def test_critical_voice_bypasses_duplicate_cooldown() -> None:
    queue = VoiceCommandQueue()
    scheduler = SpeechScheduler(queue, duplicate_cooldown_s=60)
    first = queue.submit(_command("missile warning", priority=CommandPriority.CRITICAL, agent=VoiceAgent.THREAT_ANALYZER))
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    selected = scheduler.select_next(now)
    scheduler.mark_spoken(selected.command, now)
    queue.complete(first.command_id, "spoken")
    queue.submit(_command("missile warning", priority=CommandPriority.CRITICAL, agent=VoiceAgent.THREAT_ANALYZER))

    repeated = scheduler.select_next(now + timedelta(seconds=1))
    assert repeated.decision is SpeechDecision.READY


def test_speech_api_selects_and_acknowledges_voice() -> None:
    voice_commands._commands.clear()
    speech_scheduler.reset()
    queued = voice_commands.submit(_command("Texaco, join-up stabilized."))

    with TestClient(app) as client:
        selected = client.post("/v1/speech/next")
        assert selected.status_code == 200
        payload = selected.json()
        assert payload["decision"] == "ready"
        assert payload["command"]["command_id"] == str(queued.command_id)

        spoken = client.post(f"/v1/speech/{queued.command_id}/spoken", json={"message": "played"})
        assert spoken.status_code == 200
        assert spoken.json()["state"] == "completed"

    voice_commands._commands.clear()
    speech_scheduler.reset()
