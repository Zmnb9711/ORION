from __future__ import annotations

from pydantic import BaseModel, Field

from orion.aar_rendezvous import AarPhase, AarSession, aar_rendezvous
from orion.mission_context import build_live_mission_context
from orion.voice_core import CommandState, VoiceAgent, voice_commands


class ThreatSummary(BaseModel):
    hostile_count: int = 0
    nearest_hostile_name: str | None = None
    nearest_hostile_distance_km: float | None = None
    nearest_hostile_bearing_deg: float | None = None


class SupportSummary(BaseModel):
    awacs_available: int = 0
    tankers_available: int = 0
    jtac_available: int = 0


class AgentSummary(BaseModel):
    active: list[VoiceAgent] = Field(default_factory=list)
    queued: list[VoiceAgent] = Field(default_factory=list)


class FlightRuntimeSummary(BaseModel):
    mission_available: bool = False
    mission_id: str | None = None
    mission_name: str | None = None
    theatre: str | None = None
    mission_time_s: float | None = None
    friendly_count: int = 0
    hostile_count: int = 0
    threats: ThreatSummary = Field(default_factory=ThreatSummary)
    support: SupportSummary = Field(default_factory=SupportSummary)
    aar: AarSession = Field(default_factory=AarSession)
    agents: AgentSummary = Field(default_factory=AgentSummary)
    issues: list[str] = Field(default_factory=list)


def get_flight_runtime_summary() -> FlightRuntimeSummary:
    context = build_live_mission_context()
    nearest = context.hostiles[0] if context.hostiles else None

    active_agents: list[VoiceAgent] = []
    queued_agents: list[VoiceAgent] = []
    for command in voice_commands.list():
        if command.state is CommandState.RUNNING and command.agent not in active_agents:
            active_agents.append(command.agent)
        elif command.state is CommandState.QUEUED and command.agent not in queued_agents:
            queued_agents.append(command.agent)

    return FlightRuntimeSummary(
        mission_available=context.available,
        mission_id=context.mission_id,
        mission_name=context.mission_name,
        theatre=context.theatre,
        mission_time_s=context.mission_time_s,
        friendly_count=len(context.friendlies),
        hostile_count=len(context.hostiles),
        threats=ThreatSummary(
            hostile_count=len(context.hostiles),
            nearest_hostile_name=nearest.name if nearest else None,
            nearest_hostile_distance_km=nearest.distance_km if nearest else None,
            nearest_hostile_bearing_deg=nearest.bearing_deg if nearest else None,
        ),
        support=SupportSummary(
            awacs_available=sum(item.available for item in context.awacs),
            tankers_available=sum(item.available for item in context.tankers),
            jtac_available=sum(item.available for item in context.jtac),
        ),
        aar=aar_rendezvous.snapshot(),
        agents=AgentSummary(active=active_agents, queued=queued_agents),
        issues=context.issues,
    )
