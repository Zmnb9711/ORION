from fastapi import APIRouter

from orion.orion_settings import (
    OrionSettings,
    OrionSettingsUpdate,
    orion_settings,
)

router = APIRouter(prefix="/v1/settings", tags=["ORION settings"])


@router.get("", response_model=OrionSettings)
def get_settings() -> OrionSettings:
    return orion_settings.get()


@router.patch("", response_model=OrionSettings)
def update_settings(payload: OrionSettingsUpdate) -> OrionSettings:
    return orion_settings.update(payload)


@router.post("/reset", response_model=OrionSettings)
def reset_settings() -> OrionSettings:
    return orion_settings.reset()
