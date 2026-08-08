from fastapi import APIRouter, Query

from orion.tactical_proactive import tactical_proactive
from orion.voice_core import VoiceCommand


router = APIRouter(prefix="/v1/tactical", tags=["Tactical Situation"])


@router.post("/proactive/voice", response_model=list[VoiceCommand])
def poll_tactical_voice(language: str = Query(default="en", pattern="^(ru|en)$")) -> list[VoiceCommand]:
    return tactical_proactive.poll(language=language)
