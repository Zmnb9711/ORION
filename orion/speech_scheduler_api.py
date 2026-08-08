from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.speech_scheduler import SpeechSelection, speech_scheduler
from orion.voice_core import CommandState, VoiceCommand, voice_commands


router = APIRouter(prefix="/v1/speech", tags=["Speech Scheduler"])


class SpeechComplete(BaseModel):
    message: str = Field(default="spoken", min_length=1, max_length=4000)


@router.post("/next", response_model=SpeechSelection)
def select_next_speech() -> SpeechSelection:
    return speech_scheduler.select_next()


@router.post("/{command_id}/spoken", response_model=VoiceCommand)
def mark_speech_spoken(command_id: UUID, payload: SpeechComplete) -> VoiceCommand:
    command = voice_commands.get(command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Voice command not found")
    if command.state is not CommandState.RUNNING:
        raise HTTPException(status_code=409, detail="Voice command is not running")
    speech_scheduler.mark_spoken(command)
    return voice_commands.complete(command_id, payload.message)
