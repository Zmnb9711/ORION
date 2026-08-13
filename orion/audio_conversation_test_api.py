from __future__ import annotations

from fastapi import APIRouter

from orion.audio_conversation_test import ConversationalAudioTestResult, run_conversational_audio_test


router = APIRouter(prefix="/v1/audio-test", tags=["Audio Test"])


@router.post("/conversation", response_model=ConversationalAudioTestResult)
def conversation_audio_test() -> ConversationalAudioTestResult:
    return run_conversational_audio_test()
