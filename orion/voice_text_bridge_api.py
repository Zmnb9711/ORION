from __future__ import annotations

import re

from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter(prefix="/v1/voice", tags=["Voice"])

VOICE_V01_REPLY = "Всё хорошо. Связь установлена."


class VoiceTextRequest(BaseModel):
    """Text already recognized by the external/local STT process."""

    text: str = Field(min_length=1, max_length=4000)
    source: str = "whisper"
    language: str = "auto"


class VoiceTextResponse(BaseModel):
    heard: str
    reply: str
    matched: bool
    source: str
    tts_requested: bool = True


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\wёЁ]+", text.casefold(), flags=re.UNICODE))


def _is_voice_v01_greeting(text: str) -> bool:
    words = _words(text)
    return {"привет", "как", "дела"}.issubset(words)


@router.post("/text", response_model=VoiceTextResponse)
def accept_recognized_text(payload: VoiceTextRequest) -> VoiceTextResponse:
    """Accept STT text only; microphone capture belongs to the Whisper worker.

    Voice v0.1 intentionally has no AI dependency.  Its only acceptance
    dialogue proves the STT -> Core boundary before an LLM is connected.
    """

    matched = _is_voice_v01_greeting(payload.text)
    reply = VOICE_V01_REPLY if matched else ""
    return VoiceTextResponse(
        heard=payload.text,
        reply=reply,
        matched=matched,
        source=payload.source,
        tts_requested=matched,
    )
