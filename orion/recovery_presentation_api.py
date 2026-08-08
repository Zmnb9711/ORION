from uuid import UUID

from fastapi import APIRouter, Query

from orion.recovery_presentation import RecoveryPresentation, get_recovery_presentation, start_dcs_from_presentation


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
