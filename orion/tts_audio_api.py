from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from orion.speech_scheduler import SpeechDecision, SpeechSelection, speech_scheduler
from orion.tts_audio import AudioRenderRequest, AudioRenderResult, TtsBackend, profile_for, tts_router
from orion.voice_core import CommandState, voice_commands


router = APIRouter(prefix="/v1/tts", tags=["TTS Audio"])


@router.post("/prepare-next", response_model=AudioRenderResult | SpeechSelection)
def prepare_next_tts(
    language: str = Query(default="en", pattern="^(en|ru)$"),
    backend: TtsBackend = Query(default=TtsBackend.WINDOWS_SAPI),
    output_device: str | None = Query(default=None),
) -> AudioRenderResult | SpeechSelection:
    selection = speech_scheduler.select_next()
    if selection.decision is not SpeechDecision.READY or selection.command is None:
        return selection

    command = selection.command
    request = AudioRenderRequest(
        command_id=str(command.command_id),
        text=command.transcript,
        agent=command.agent,
        profile=profile_for(command, language),
        backend=backend,
        output_device=output_device,
    )
    result = tts_router.render(request)
    if not result.accepted:
        voice_commands.fail(command.command_id, result.message)
    return result


@router.post("/{command_id}/failed")
def mark_tts_failed(command_id: UUID, message: str = Query(min_length=1, max_length=4000)):
    command = voice_commands.get(command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Voice command not found")
    if command.state is not CommandState.RUNNING:
        raise HTTPException(status_code=409, detail="Voice command is not running")
    return voice_commands.fail(command_id, message)
