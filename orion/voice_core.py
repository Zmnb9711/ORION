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
        with self._lock:
            if command.priority is CommandPriority.CRITICAL:
                for current in self._commands.values():
                    if current.state is CommandState.RUNNING and current.priority < CommandPriority.CRITICAL:
                        current.state = CommandState.CANCELLED
                        current.error = "Preempted by critical command"
                        current.updated_at = datetime.now(UTC)
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
            command.state = CommandState.RUNNING
            command.updated_at = datetime.now(UTC)
            return command.model_copy(deep=True)

    def start_next(self) -> VoiceCommand | None:
        with self._lock:
            queued = [item for item in self._commands.values() if item.state is CommandState.QUEUED]
            if not queued:
                return None
            command = sorted(queued, key=lambda item: (-int(item.priority), item.created_at))[0]
            command.state = CommandState.RUNNING
            command.updated_at = datetime.now(UTC)
            return command.model_copy(deep=True)

    def complete(self, command_id: UUID, result: str) -> VoiceCommand:
        return self._finish(command_id, CommandState.COMPLETED, result=result)

    def fail(self, command_id: UUID, error: str) -> VoiceCommand:
        return self._finish(command_id, CommandState.FAILED, error=error)

    def cancel(self, command_id: UUID) -> VoiceCommand:
        return self._finish(command_id, CommandState.CANCELLED)

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
