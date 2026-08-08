from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from orion.voice_core import VoiceAgent, VoiceCommand


class TtsBackend(StrEnum):
    WINDOWS_SAPI = "windows_sapi"
    EXTERNAL = "external"


class VoiceProfile(BaseModel):
    profile_id: str
    locale: str = "en-US"
    voice_name: str | None = None
    voice_slot: int = Field(default=0, ge=0)
    persona: str = "orion"
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    radio_effect: bool = False


class AudioRenderRequest(BaseModel):
    command_id: str
    text: str
    agent: VoiceAgent
    profile: VoiceProfile
    backend: TtsBackend = TtsBackend.WINDOWS_SAPI
    output_device: str | None = None


class AudioRenderResult(BaseModel):
    accepted: bool
    backend: TtsBackend
    command_id: str
    output_path: str | None = None
    message: str


class TtsAdapter(Protocol):
    def render(self, request: AudioRenderRequest) -> AudioRenderResult: ...


class WindowsSapiContractAdapter:
    """Windows-facing contract for local TTS.

    This adapter intentionally does not invoke COM/audio APIs in the server process yet.
    It produces a deterministic render contract that a Windows worker can consume.
    """

    def __init__(self, spool_dir: str = "runtime/tts") -> None:
        self._spool_dir = Path(spool_dir)

    def render(self, request: AudioRenderRequest) -> AudioRenderResult:
        target = self._spool_dir / f"{request.command_id}.wav"
        return AudioRenderResult(
            accepted=True,
            backend=TtsBackend.WINDOWS_SAPI,
            command_id=request.command_id,
            output_path=str(target),
            message="TTS render accepted for Windows audio worker",
        )


class TtsRouter:
    def __init__(self) -> None:
        self._adapters: dict[TtsBackend, TtsAdapter] = {
            TtsBackend.WINDOWS_SAPI: WindowsSapiContractAdapter(),
        }

    def render(self, request: AudioRenderRequest) -> AudioRenderResult:
        adapter = self._adapters.get(request.backend)
        if adapter is None:
            return AudioRenderResult(
                accepted=False,
                backend=request.backend,
                command_id=request.command_id,
                message="No TTS adapter registered for backend",
            )
        return adapter.render(request)


def profile_for(command: VoiceCommand, language: str | None = None) -> VoiceProfile:
    locale = "ru-RU" if language == "ru" else "en-US"
    # voice_slot is a deterministic preference among installed voices for the locale.
    # It makes mission roles audibly distinct when Windows has multiple voices while
    # preserving a safe fallback on systems with only one installed voice.
    profiles: dict[VoiceAgent, VoiceProfile] = {
        VoiceAgent.ATC: VoiceProfile(profile_id="atc", persona="controller", voice_slot=0, locale=locale, rate=0.95, radio_effect=True),
        VoiceAgent.AWACS: VoiceProfile(profile_id="awacs", persona="airborne_controller", voice_slot=2, locale=locale, rate=0.92, radio_effect=True),
        VoiceAgent.TANKER: VoiceProfile(profile_id="tanker", persona="tanker_crew", voice_slot=3, locale=locale, rate=0.95, radio_effect=True),
        VoiceAgent.JTAC: VoiceProfile(profile_id="jtac", persona="ground_jtac", voice_slot=1, locale=locale, rate=0.90, volume=0.96, radio_effect=True),
        VoiceAgent.MISSION_CONTROL: VoiceProfile(profile_id="mission_control", persona="mission_control", voice_slot=4, locale=locale, rate=0.96),
        VoiceAgent.COALITION_AIRCRAFT: VoiceProfile(profile_id="coalition_aircraft", persona="coalition_aircraft", voice_slot=5, locale=locale, rate=1.0, radio_effect=True),
        VoiceAgent.COALITION_HELICOPTERS: VoiceProfile(profile_id="coalition_helicopters", persona="coalition_helicopter", voice_slot=6, locale=locale, rate=0.98, radio_effect=True),
        VoiceAgent.COALITION_GROUND: VoiceProfile(profile_id="coalition_ground", persona="ground_unit", voice_slot=7, locale=locale, rate=0.97, radio_effect=True),
        VoiceAgent.COALITION_NAVAL: VoiceProfile(profile_id="coalition_naval", persona="naval_unit", voice_slot=8, locale=locale, rate=0.96, radio_effect=True),
        VoiceAgent.THREAT_ANALYZER: VoiceProfile(profile_id="threat", persona="threat_analyzer", voice_slot=9, locale=locale, rate=1.08),
        VoiceAgent.SYSTEM: VoiceProfile(profile_id="orion", persona="orion", voice_slot=10, locale=locale, rate=1.0),
    }
    return profiles.get(command.agent, VoiceProfile(profile_id=command.agent.value, persona=command.agent.value, locale=locale))


tts_router = TtsRouter()
