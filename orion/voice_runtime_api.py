from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orion.audio_conversation_test import ConversationalAudioTestResult
from orion.voice_runtime import VoiceRuntimeStatus, voice_runtime

router = APIRouter(prefix="/v1/voice-runtime", tags=["Voice Runtime"])


@router.get("/status", response_model=VoiceRuntimeStatus)
def voice_runtime_status() -> VoiceRuntimeStatus:
    return voice_runtime.status()


@router.post("/ensure", response_model=VoiceRuntimeStatus)
def ensure_voice_runtime() -> VoiceRuntimeStatus:
    try:
        return voice_runtime.ensure_ready()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/test/conversation", response_model=ConversationalAudioTestResult)
def test_voice_runtime() -> ConversationalAudioTestResult:
    try:
        return ConversationalAudioTestResult.model_validate(voice_runtime.conversation_test())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/shutdown", response_model=VoiceRuntimeStatus)
def shutdown_voice_runtime() -> VoiceRuntimeStatus:
    return voice_runtime.shutdown()
