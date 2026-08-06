from fastapi import APIRouter

from orion.orion_settings import (
    OrionSettings,
    OrionSettingsUpdate,
    orion_settings,
)
from orion.settings_help import SETTINGS_HELP, SettingsHelpCatalog

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


@router.get("/help", response_model=SettingsHelpCatalog)
def get_settings_help() -> SettingsHelpCatalog:
    return SETTINGS_HELP
