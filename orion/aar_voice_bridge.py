from __future__ import annotations

from pydantic import BaseModel

from orion.aar_runtime_monitor import AarRuntimeMonitor, AarRuntimeMonitorResult, aar_runtime_monitor
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, VoiceCommandQueue, voice_commands


class AarVoiceBridgeResult(BaseModel):
    monitor: AarRuntimeMonitorResult
    enqueued: VoiceCommand | None = None


class AarVoiceBridge:
    """Publishes sparse proactive AAR callouts into the shared Voice Core queue."""

    def __init__(self, monitor: AarRuntimeMonitor, queue: VoiceCommandQueue) -> None:
        self._monitor = monitor
        self._queue = queue

    def poll_and_enqueue(self, language: str = "en") -> AarVoiceBridgeResult:
        result = self._monitor.poll(language)
        update = result.update
        if not update.should_announce or not update.spoken_text:
            return AarVoiceBridgeResult(monitor=result)

        reason = update.reason or "update"
        command = self._queue.submit(
            VoiceCommandCreate(
                transcript=update.spoken_text,
                intent=f"aar_proactive:{reason}",
                agent=VoiceAgent.TANKER,
                priority=_priority(reason),
                context={
                    "aar_phase": update.phase.value,
                    "reason": reason,
                    "language": language,
                    "active_tanker_present": result.active_tanker_present,
                },
            )
        )
        return AarVoiceBridgeResult(monitor=result, enqueued=command)


def _priority(reason: str) -> CommandPriority:
    if reason in {
        "active_tanker_lost",
        "contact_envelope_lost",
        "closure_excessive",
    }:
        return CommandPriority.HIGH
    return CommandPriority.NORMAL


aar_voice_bridge = AarVoiceBridge(aar_runtime_monitor, voice_commands)
