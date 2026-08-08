from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand


class SpeechLane(StrEnum):
    RADIO = "radio"
    INTERCOM = "intercom"
    SYSTEM = "system"


class InterruptPolicy(StrEnum):
    NEVER = "never"
    LOWER_PRIORITY = "lower_priority"
    ALWAYS = "always"


class DuckingPolicy(StrEnum):
    NONE = "none"
    MUSIC = "music"
    NON_RADIO = "non_radio"
    ALL = "all"


class VoicePlaybackPolicy(BaseModel):
    lane: SpeechLane
    interrupt: InterruptPolicy
    ducking: DuckingPolicy
    radio_effect: bool = False
    allow_overlap: bool = False


_RADIO_AGENTS = {
    VoiceAgent.ATC,
    VoiceAgent.AWACS,
    VoiceAgent.TANKER,
    VoiceAgent.JTAC,
    VoiceAgent.FLIGHT,
    VoiceAgent.WINGMAN,
    VoiceAgent.COALITION_AIRCRAFT,
    VoiceAgent.COALITION_HELICOPTERS,
    VoiceAgent.COALITION_GROUND,
    VoiceAgent.COALITION_NAVAL,
}

_INTERCOM_AGENTS = {
    VoiceAgent.MISSION_CONTROL,
    VoiceAgent.NAVIGATION,
    VoiceAgent.THREAT_ANALYZER,
    VoiceAgent.FLIGHT_ADVISOR,
    VoiceAgent.CHECKLIST,
    VoiceAgent.GENERAL_CONVERSATION,
}


def resolve_voice_policy(command: VoiceCommand) -> VoicePlaybackPolicy:
    if command.agent is VoiceAgent.SYSTEM:
        lane = SpeechLane.SYSTEM
    elif command.agent in _RADIO_AGENTS:
        lane = SpeechLane.RADIO
    elif command.agent in _INTERCOM_AGENTS:
        lane = SpeechLane.INTERCOM
    else:
        lane = SpeechLane.INTERCOM

    if command.priority is CommandPriority.CRITICAL:
        interrupt = InterruptPolicy.ALWAYS
        ducking = DuckingPolicy.ALL
    elif command.priority is CommandPriority.HIGH:
        interrupt = InterruptPolicy.LOWER_PRIORITY
        ducking = DuckingPolicy.NON_RADIO if lane is SpeechLane.RADIO else DuckingPolicy.MUSIC
    else:
        interrupt = InterruptPolicy.NEVER
        ducking = DuckingPolicy.MUSIC if lane is SpeechLane.RADIO else DuckingPolicy.NONE

    return VoicePlaybackPolicy(
        lane=lane,
        interrupt=interrupt,
        ducking=ducking,
        radio_effect=lane is SpeechLane.RADIO,
        allow_overlap=False,
    )
