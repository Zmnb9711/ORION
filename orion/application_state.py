from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.flight_runtime_summary import FlightRuntimeSummary, get_flight_runtime_summary
from orion.mission_command_status import MissionCommandStatus, mission_command_statuses
from orion.startup_health import StartupHealthReport, StartupHealthState, inspect_startup_health
from orion.telemetry_handshake import telemetry_handshake
from orion.voice_core import CommandState, voice_commands
from orion.windows_audio_worker import AudioPlaybackStatus, windows_audio_worker


class ApplicationReadiness(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    ACTION_REQUIRED = "action_required"


class MissionBridgeSummary(BaseModel):
    pending: int = 0
    failed: int = 0
    latest_status: MissionCommandStatus | None = None


class VoiceSummary(BaseModel):
    queued: int = 0
    running: int = 0
    failed: int = 0


class OrionApplicationState(BaseModel):
    readiness: ApplicationReadiness
    dcs_connected: bool
    aircraft_type: str | None = None
    startup_health: StartupHealthReport
    mission_bridge: MissionBridgeSummary = Field(default_factory=MissionBridgeSummary)
    voice: VoiceSummary = Field(default_factory=VoiceSummary)
    audio: AudioPlaybackStatus
    flight: FlightRuntimeSummary = Field(default_factory=FlightRuntimeSummary)


def get_application_state() -> OrionApplicationState:
    health = inspect_startup_health()
    telemetry = telemetry_handshake.snapshot()

    mission_items = mission_command_statuses.list()
    mission = MissionBridgeSummary(
        pending=sum(item.status in {MissionCommandStatus.QUEUED, MissionCommandStatus.ACCEPTED} for item in mission_items),
        failed=sum(item.status is MissionCommandStatus.FAILED for item in mission_items),
        latest_status=mission_items[0].status if mission_items else None,
    )

    voice_items = voice_commands.list()
    voice = VoiceSummary(
        queued=sum(item.state is CommandState.QUEUED for item in voice_items),
        running=sum(item.state is CommandState.RUNNING for item in voice_items),
        failed=sum(item.state is CommandState.FAILED for item in voice_items),
    )

    flight = get_flight_runtime_summary()

    if health.state is StartupHealthState.ACTION_REQUIRED:
        readiness = ApplicationReadiness.ACTION_REQUIRED
    elif health.state is StartupHealthState.DEGRADED or mission.failed or voice.failed:
        readiness = ApplicationReadiness.DEGRADED
    else:
        readiness = ApplicationReadiness.READY

    return OrionApplicationState(
        readiness=readiness,
        dcs_connected=telemetry.connected,
        aircraft_type=telemetry.aircraft_type,
        startup_health=health,
        mission_bridge=mission,
        voice=voice,
        audio=windows_audio_worker.status(),
        flight=flight,
    )
