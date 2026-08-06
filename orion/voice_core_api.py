from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.voice_core import VoiceCommand, VoiceCommandCreate, voice_commands
from orion.voice_understanding import ParsedVoiceRequest, parse_transcript

router = APIRouter(prefix="/v1/voice-commands", tags=["Voice Core"])


class VoiceCommandResult(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class VoiceTranscript(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)


class SubmittedTranscript(BaseModel):
    parsed: ParsedVoiceRequest
    commands: list[VoiceCommand]


@router.post("", response_model=VoiceCommand, status_code=201)
def submit_voice_command(payload: VoiceCommandCreate) -> VoiceCommand:
    return voice_commands.submit(payload)


@router.post("/understand", response_model=ParsedVoiceRequest)
def understand_voice_transcript(payload: VoiceTranscript) -> ParsedVoiceRequest:
    return parse_transcript(payload.transcript)


@router.post("/submit-transcript", response_model=SubmittedTranscript, status_code=201)
def submit_voice_transcript(payload: VoiceTranscript) -> SubmittedTranscript:
    parsed = parse_transcript(payload.transcript)
    commands = [voice_commands.submit(command) for command in parsed.commands]
    return SubmittedTranscript(parsed=parsed, commands=commands)


@router.get("", response_model=list[VoiceCommand])
def list_voice_commands() -> list[VoiceCommand]:
    return voice_commands.list()


@router.get("/{command_id}", response_model=VoiceCommand)
def get_voice_command(command_id: UUID) -> VoiceCommand:
    command = voice_commands.get(command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Voice command not found")
    return command


@router.post("/next", response_model=VoiceCommand | None)
def start_next_voice_command() -> VoiceCommand | None:
    return voice_commands.start_next()


@router.post("/{command_id}/complete", response_model=VoiceCommand)
def complete_voice_command(command_id: UUID, payload: VoiceCommandResult) -> VoiceCommand:
    try:
        return voice_commands.complete(command_id, payload.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{command_id}/fail", response_model=VoiceCommand)
def fail_voice_command(command_id: UUID, payload: VoiceCommandResult) -> VoiceCommand:
    try:
        return voice_commands.fail(command_id, payload.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{command_id}/cancel", response_model=VoiceCommand)
def cancel_voice_command(command_id: UUID) -> VoiceCommand:
    try:
        return voice_commands.cancel(command_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
