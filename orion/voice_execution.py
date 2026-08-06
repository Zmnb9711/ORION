from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field

from orion.voice_core import VoiceAgent, VoiceCommand


class ExecutionState(StrEnum):
    ACCEPTED = "accepted"
    BRIDGE_REQUIRED = "bridge_required"
    COMPLETED = "completed"
    REJECTED = "rejected"


class ExecutionOutcome(BaseModel):
    state: ExecutionState
    agent: VoiceAgent
    intent: str
    adapter: str
    message: str
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class VoiceCommandExecutor(Protocol):
    def execute(self, command: VoiceCommand) -> ExecutionOutcome: ...


class BridgeExecutor:
    """Builds a command envelope for modules that require DCS/Mission Bridge."""

    def __init__(self, adapter: str) -> None:
        self.adapter = adapter

    def execute(self, command: VoiceCommand) -> ExecutionOutcome:
        return ExecutionOutcome(
            state=ExecutionState.BRIDGE_REQUIRED,
            agent=command.agent,
            intent=command.intent,
            adapter=self.adapter,
            message="Command accepted and requires an active DCS or Mission Bridge adapter",
            payload={
                "command_id": str(command.command_id),
                "transcript": command.transcript,
                **command.context,
            },
        )


class ConversationExecutor:
    def execute(self, command: VoiceCommand) -> ExecutionOutcome:
        return ExecutionOutcome(
            state=ExecutionState.ACCEPTED,
            agent=command.agent,
            intent=command.intent,
            adapter="ai-dialogue",
            message="Command accepted by the dialogue engine",
            payload={"command_id": str(command.command_id), "transcript": command.transcript},
        )


class SystemExecutor:
    def execute(self, command: VoiceCommand) -> ExecutionOutcome:
        return ExecutionOutcome(
            state=ExecutionState.ACCEPTED,
            agent=command.agent,
            intent=command.intent,
            adapter="orion-system",
            message="System command accepted",
            payload={"command_id": str(command.command_id)},
        )


class VoiceExecutionDispatcher:
    def __init__(self) -> None:
        bridge_agents = {
            VoiceAgent.ATC: "virtual-atc",
            VoiceAgent.AWACS: "awacs-service",
            VoiceAgent.TANKER: "tanker-service",
            VoiceAgent.JTAC: "jtac-service",
            VoiceAgent.MISSION_CONTROL: "mission-control",
            VoiceAgent.NAVIGATION: "navigation-service",
            VoiceAgent.THREAT_ANALYZER: "threat-analyzer",
            VoiceAgent.FLIGHT_ADVISOR: "flight-advisor",
            VoiceAgent.CHECKLIST: "checklist-service",
            VoiceAgent.WINGMAN: "dcs-command-translator",
            VoiceAgent.FLIGHT: "dcs-command-translator",
            VoiceAgent.COALITION_AIRCRAFT: "dcs-capability-translator",
            VoiceAgent.COALITION_HELICOPTERS: "dcs-capability-translator",
            VoiceAgent.COALITION_GROUND: "dcs-capability-translator",
            VoiceAgent.COALITION_NAVAL: "dcs-capability-translator",
        }
        self._executors: dict[VoiceAgent, VoiceCommandExecutor] = {
            agent: BridgeExecutor(adapter) for agent, adapter in bridge_agents.items()
        }
        self._executors[VoiceAgent.GENERAL_CONVERSATION] = ConversationExecutor()
        self._executors[VoiceAgent.SYSTEM] = SystemExecutor()

    def execute(self, command: VoiceCommand) -> ExecutionOutcome:
        executor = self._executors.get(command.agent)
        if executor is None:
            return ExecutionOutcome(
                state=ExecutionState.REJECTED,
                agent=command.agent,
                intent=command.intent,
                adapter="none",
                message="No executor is registered for this agent",
            )
        return executor.execute(command)

    def adapters(self) -> dict[str, str]:
        return {
            agent.value: getattr(executor, "adapter", executor.__class__.__name__)
            for agent, executor in self._executors.items()
        }


voice_execution = VoiceExecutionDispatcher()
