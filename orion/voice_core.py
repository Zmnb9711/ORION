from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class VoiceAgent(StrEnum):
    ATC = "atc"
    AWACS = "awacs"
    TANKER = "tanker"
    JTAC = "jtac"
    MISSION_CONTROL = "mission_control"
    NAVIGATION = "navigation"
    THREAT_ANALYZER = "threat_analyzer"
    FLIGHT_ADVISOR = "flight_advisor"
    CHECKLIST = "checklist"
    WINGMAN = "wingman"
    FLIGHT = "flight"
    COALITION_AIRCRAFT = "coalition_aircraft"
    COALITION_HELICOPTERS = "coalition_helicopters"
    COALITION_GROUND = "coalition_ground"
    COALITION_NAVAL = "coalition_naval"
    GENERAL_CONVERSATION = "general_conversation"
    SYSTEM = "system"


class CommandPriority(IntEnum):
    LOW = 10
    NORMAL = 20
    HIGH = 30
    CRITICAL = 40


class CommandState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VoiceCommandCreate(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)
    intent: str = Field(min_length=1, max_length=120)
    agent: VoiceAgent
    priority: CommandPriority = CommandPriority.NORMAL
    context: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class VoiceCommand(BaseModel):
    command_id: UUID = Field(default_factory=uuid4)
    transcript: str
    intent: str
    agent: VoiceAgent
    priority: CommandPriority
    context: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    state: CommandState = CommandState.QUEUED
    result: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VoiceCommandQueue:
    def __init__(self) -> None:
        self._commands: dict[UUID, VoiceCommand] = {}
        self._lock = RLock()

    def submit(self, payload: VoiceCommandCreate) -> VoiceCommand:
        command = VoiceCommand(**payload.model_dump())
        policy = self._resolve_policy(command)
        command.context = {
            **command.context,
            "speech_lane": policy.lane.value,
            "interrupt_policy": policy.interrupt.value,
            "ducking_policy": policy.ducking.value,
            "radio_effect": policy.radio_effect,
            "allow_overlap": policy.allow_overlap,
        }
        with self._lock:
            self._apply_preemption(command, policy)
            self._commands[command.command_id] = command
            return command.model_copy(deep=True)

    def list(self) -> list[VoiceCommand]:
        with self._lock:
            return [item.model_copy(deep=True) for item in sorted(
                self._commands.values(), key=lambda item: (-int(item.priority), item.created_at)
            )]

    def get(self, command_id: UUID) -> VoiceCommand | None:
        with self._lock:
            command = self._commands.get(command_id)
            return command.model_copy(deep=True) if command else None

    def start(self, command_id: UUID) -> VoiceCommand:
        with self._lock:
            command = self._commands.get(command_id)
            if command is None:
                raise KeyError("Voice command not found")
            if command.state is not CommandState.QUEUED:
                raise ValueError("Voice command is not queued")
            self._prepare_start(command)
            command.state = CommandState.RUNNING
            command.updated_at = datetime.now(UTC)
            return command.model_copy(deep=True)

    def start_next(self) -> VoiceCommand | None:
        with self._lock:
            queued = [item for item in self._commands.values() if item.state is CommandState.QUEUED]
            if not queued:
                return None
            command = sorted(queued, key=lambda item: (-int(item.priority), item.created_at))[0]
            self._prepare_start(command)
            command.state = CommandState.RUNNING
            command.updated_at = datetime.now(UTC)
            return command.model_copy(deep=True)

    def complete(self, command_id: UUID, result: str) -> VoiceCommand:
        return self._finish(command_id, CommandState.COMPLETED, result=result)

    def fail(self, command_id: UUID, error: str) -> VoiceCommand:
        return self._finish(command_id, CommandState.FAILED, error=error)

    def cancel(self, command_id: UUID) -> VoiceCommand:
        return self._finish(command_id, CommandState.CANCELLED)

    def _prepare_start(self, command: VoiceCommand) -> None:
        policy = self._resolve_policy(command)
        self._apply_preemption(command, policy)
        if not policy.allow_overlap:
            running = [item for item in self._commands.values() if item.state is CommandState.RUNNING]
            if running and not any(item.command_id == command.command_id for item in running):
                # If policy did not authorize interruption, keep serialization strict.
                if not self._can_interrupt_any(command, policy, running):
                    raise ValueError("Another voice command is already running")

    def _apply_preemption(self, command: VoiceCommand, policy) -> None:
        running = [item for item in self._commands.values() if item.state is CommandState.RUNNING]
        for current in running:
            if self._can_interrupt(command, policy, current):
                current.state = CommandState.CANCELLED
                current.error = f"Preempted by {command.priority.name.lower()} voice command"
                current.updated_at = datetime.now(UTC)

    def _can_interrupt_any(self, command: VoiceCommand, policy, running: list[VoiceCommand]) -> bool:
        return any(self._can_interrupt(command, policy, current) for current in running)

    @staticmethod
    def _can_interrupt(command: VoiceCommand, policy, current: VoiceCommand) -> bool:
        from orion.voice_policy import InterruptPolicy

        if policy.interrupt is InterruptPolicy.ALWAYS:
            return True
        if policy.interrupt is InterruptPolicy.LOWER_PRIORITY:
            return command.priority > current.priority
        return False

    @staticmethod
    def _resolve_policy(command: VoiceCommand):
        # Lazy import avoids a module cycle because voice_policy depends on core types.
        from orion.voice_policy import resolve_voice_policy

        return resolve_voice_policy(command)

    def _finish(
        self,
        command_id: UUID,
        state: CommandState,
        result: str | None = None,
        error: str | None = None,
    ) -> VoiceCommand:
        with self._lock:
            command = self._commands.get(command_id)
            if command is None:
                raise KeyError("Voice command not found")
            if command.state in {CommandState.COMPLETED, CommandState.FAILED, CommandState.CANCELLED}:
                raise ValueError("Voice command is already final")
            command.state = state
            command.result = result
            command.error = error
            command.updated_at = datetime.now(UTC)
            return command.model_copy(deep=True)


voice_commands = VoiceCommandQueue()
