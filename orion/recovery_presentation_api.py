from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from orion.recovery_presentation import RecoveryPresentation, get_recovery_presentation, start_dcs_from_presentation
from orion.recovery_stream_api import _recovery_stream


router = APIRouter(prefix="/v1/recovery-ui", tags=["Startup Recovery UI"])


@router.get("", response_model=RecoveryPresentation)
def recovery_ui_state(
    launch_id: UUID | None = None,
    language: str = Query(default="ru", pattern="^(ru|en)$"),
) -> RecoveryPresentation:
    return get_recovery_presentation(launch_id=launch_id, language=language)


@router.post("/start-dcs", response_model=RecoveryPresentation)
def recovery_ui_start_dcs(language: str = Query(default="ru", pattern="^(ru|en)$")) -> RecoveryPresentation:
    return start_dcs_from_presentation(language=language)


@router.get("/stream")
def stream_recovery_ui(
    request: Request,
    launch_id: UUID | None = Query(default=None),
    language: str = Query(default="ru", pattern="^(ru|en)$"),
    heartbeat_seconds: float = Query(default=15.0, ge=1.0, le=60.0),
    poll_seconds: float = Query(default=0.5, ge=0.1, le=5.0),
) -> StreamingResponse:
    return StreamingResponse(
        _recovery_stream(request, launch_id, language, heartbeat_seconds, poll_seconds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
