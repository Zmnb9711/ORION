from __future__ import annotations

from enum import StrEnum
from threading import RLock

from pydantic import BaseModel, Field


class InterfaceLanguage(StrEnum):
    RU = "ru"
    EN = "en"


class ResponseDetail(StrEnum):
    BRIEF = "brief"
    BALANCED = "balanced"
    DETAILED = "detailed"


class OrionSettings(BaseModel):
    interface_language: InterfaceLanguage = InterfaceLanguage.RU
    assistant_language: InterfaceLanguage = InterfaceLanguage.RU
    response_detail: ResponseDetail = ResponseDetail.BALANCED
    free_speech_mode: bool = True
    aviation_phraseology: bool = True
    conversation_memory: bool = True
    auto_prepare_mission_copy: bool = False
    minimize_console_after_launch: bool = False
    notifications_enabled: bool = True
    default_installation_id: str | None = None
    default_profile_id: str | None = None
    assistant_name: str = Field(default="ORION", min_length=1, max_length=40)


class OrionSettingsUpdate(BaseModel):
    interface_language: InterfaceLanguage | None = None
    assistant_language: InterfaceLanguage | None = None
    response_detail: ResponseDetail | None = None
    free_speech_mode: bool | None = None
    aviation_phraseology: bool | None = None
    conversation_memory: bool | None = None
    auto_prepare_mission_copy: bool | None = None
    minimize_console_after_launch: bool | None = None
    notifications_enabled: bool | None = None
    default_installation_id: str | None = None
    default_profile_id: str | None = None
    assistant_name: str | None = Field(default=None, min_length=1, max_length=40)


class OrionSettingsStore:
    def __init__(self) -> None:
        self._settings = OrionSettings()
        self._lock = RLock()

    def get(self) -> OrionSettings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update(self, payload: OrionSettingsUpdate) -> OrionSettings:
        with self._lock:
            changes = payload.model_dump(exclude_none=True)
            self._settings = self._settings.model_copy(update=changes)
            return self._settings.model_copy(deep=True)

    def reset(self) -> OrionSettings:
        with self._lock:
            self._settings = OrionSettings()
            return self._settings.model_copy(deep=True)


orion_settings = OrionSettingsStore()
