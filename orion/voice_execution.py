from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field

from orion.voice_core import VoiceAgent, VoiceCommand
from orion.voice_mission_queries import execute_mission_query


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
    payload: dict[str, object] = Field(default_factory=dict)


class VoiceCommandExecutor(Protocol):
    def execute(self, command: VoiceCommand) -> ExecutionOutcome: ...


class BridgeExecutor:
    def __init__(self, adapter: str) -> None:
        self.adapter = adapter

    def execute(self, command: VoiceCommand) -> ExecutionOutcome:
        return ExecutionOutcome(
            state=ExecutionState.BRIDGE_REQUIRED,
            agent=command.agent,
            intent=command.intent,
            adapter=self.adapter,
            message="Command accepted and requires an active DCS or Mission Bridge adapter",
            payload={"command_id": str(command.command_id), "transcript": command.transcript, **command.context},
        )


class MissionInformationExecutor:
    adapter = "mission-information"
    supported_intents = {
        "find_unit_frequency",
        "find_unit_callsign",
        "find_unit_callsigns_near_landmark",
        "find_unit_position",
        "show_unit_on_map",
        "find_radio_preset_channel",
        "find_rsbn_channel",
        "find_adf_channel",
    }

    def execute(self, command: VoiceCommand) -> ExecutionOutcome:
        result = execute_mission_query(command)
        return ExecutionOutcome(
            state=ExecutionState.COMPLETED if result.completed else ExecutionState.REJECTED,
            agent=command.agent,
            intent=command.intent,
            adapter=self.adapter,
            message=result.spoken_text,
            payload={"command_id": str(command.command_id), "spoken_text": result.spoken_text, **result.data},
        )


class ConversationExecutor:
    adapter = "ai-dialogue"

    def execute(self, command: VoiceCommand) -> ExecutionOutcome:
        return ExecutionOutcome(state=ExecutionState.ACCEPTED, agent=command.agent, intent=command.intent, adapter=self.adapter, message="Command accepted by the dialogue engine", payload={"command_id": str(command.command_id), "transcript": command.transcript})


class SystemExecutor:
    adapter = "orion-system"

    def execute(self, command: VoiceCommand) -> ExecutionOutcome:
        return ExecutionOutcome(state=ExecutionState.ACCEPTED, agent=command.agent, intent=command.intent, adapter=self.adapter, message="System command accepted", payload={"command_id": str(command.command_id)})


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
        self._executors: dict[VoiceAgent, VoiceCommandExecutor] = {agent: BridgeExecutor(adapter) for agent, adapter in bridge_agents.items()}
        self._mission_information = MissionInformationExecutor()
        self._executors[VoiceAgent.GENERAL_CONVERSATION] = ConversationExecutor()
        self._executors[VoiceAgent.SYSTEM] = SystemExecutor()

    def execute(self, command: VoiceCommand) -> ExecutionOutcome:
        if command.intent in self._mission_information.supported_intents:
            return self._mission_information.execute(command)
        executor = self._executors.get(command.agent)
        if executor is None:
            return ExecutionOutcome(state=ExecutionState.REJECTED, agent=command.agent, intent=command.intent, adapter="none", message="No executor is registered for this agent")
        return executor.execute(command)

    def adapters(self) -> dict[str, str]:
        adapters = {agent.value: getattr(executor, "adapter", executor.__class__.__name__) for agent, executor in self._executors.items()}
        adapters["mission_information"] = self._mission_information.adapter
        return adapters


voice_execution = VoiceExecutionDispatcher()
