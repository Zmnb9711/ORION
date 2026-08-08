from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock

from pydantic import BaseModel, Field

from orion.voice_core import CommandPriority, CommandState, VoiceCommand, VoiceCommandQueue, voice_commands


class SpeechDecision(StrEnum):
    READY = "ready"
    IDLE = "idle"
    COOLDOWN = "cooldown"


class SpeechSelection(BaseModel):
    decision: SpeechDecision
    command: VoiceCommand | None = None
    reason: str | None = None
    interrupt_current: bool = False


class SpeechScheduler:
    """Selects queued voice commands for TTS without owning the audio backend."""

    def __init__(self, queue: VoiceCommandQueue | None = None, duplicate_cooldown_s: float = 8.0) -> None:
        self._queue = queue or voice_commands
        self._duplicate_cooldown = timedelta(seconds=duplicate_cooldown_s)
        self._last_spoken: dict[tuple[str, str], datetime] = {}
        self._lock = RLock()

    def reset(self) -> None:
        with self._lock:
            self._last_spoken.clear()

    def select_next(self, now: datetime | None = None) -> SpeechSelection:
        now = now or datetime.now(UTC)
        with self._lock:
            queued = [item for item in self._queue.list() if item.state is CommandState.QUEUED]
            if not queued:
                return SpeechSelection(decision=SpeechDecision.IDLE, reason="no_queued_voice")

            running = [item for item in self._queue.list() if item.state is CommandState.RUNNING]
            current = running[0] if running else None

            for command in queued:
                if self._in_cooldown(command, now) and command.priority < CommandPriority.CRITICAL:
                    continue
                interrupt = current is not None and command.priority > current.priority
                started = self._queue.start(command.command_id)
                return SpeechSelection(
                    decision=SpeechDecision.READY,
                    command=started,
                    reason="higher_priority_preemption" if interrupt else "next_queued_voice",
                    interrupt_current=interrupt,
                )

            return SpeechSelection(decision=SpeechDecision.COOLDOWN, reason="all_queued_voice_in_duplicate_cooldown")

    def mark_spoken(self, command: VoiceCommand, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        key = self._dedupe_key(command)
        with self._lock:
            self._last_spoken[key] = now

    def _in_cooldown(self, command: VoiceCommand, now: datetime) -> bool:
        last = self._last_spoken.get(self._dedupe_key(command))
        return last is not None and now - last < self._duplicate_cooldown

    @staticmethod
    def _dedupe_key(command: VoiceCommand) -> tuple[str, str]:
        return command.agent.value, command.transcript.strip().casefold()


speech_scheduler = SpeechScheduler()
