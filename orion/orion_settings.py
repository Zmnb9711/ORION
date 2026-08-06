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


class CommunicationMode(StrEnum):
    AVIATION_ENGLISH = "aviation_english"
    AVIATION_RUSSIAN = "aviation_russian"
    FREE_COMMUNICATION = "free_communication"


class VoiceGender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class UnpreparedMissionAction(StrEnum):
    ASK = "ask"
    PREPARE_COPY = "prepare_copy"
    LAUNCH_WITHOUT_MISSION_PACK = "launch_without_mission_pack"


class OrionSettings(BaseModel):
    # Interface and AI behavior owned by ORION.
    interface_language: InterfaceLanguage = InterfaceLanguage.RU
    response_detail: ResponseDetail = ResponseDetail.BALANCED
    conversation_memory: bool = True
    notifications_enabled: bool = True
    minimize_console_after_launch: bool = False
    assistant_name: str = Field(default="ORION", min_length=1, max_length=40)

    # Voice settings. Callsign is intentionally absent: ORION receives it from DCS.
    communication_mode: CommunicationMode = CommunicationMode.AVIATION_RUSSIAN
    voice_gender: VoiceGender = VoiceGender.MALE
    voice_variant: str = Field(default="default", min_length=1, max_length=80)
    microphone_id: str = Field(default="windows-default", min_length=1, max_length=300)
    random_conversations: bool = False

    # Mission Pack behavior. Original .miz files are never modified.
    unprepared_mission_action: UnpreparedMissionAction = UnpreparedMissionAction.ASK
    create_mission_backup: bool = True
    prepared_mission_suffix: str = Field(default=" (ORION)", min_length=1, max_length=40)
    verify_mission_pack_before_launch: bool = True
    additional_mission_directories: list[str] = Field(default_factory=list)

    # References to ORION-managed launch configuration.
    default_installation_id: str | None = None
    default_profile_id: str | None = None


class OrionSettingsUpdate(BaseModel):
    interface_language: InterfaceLanguage | None = None
    response_detail: ResponseDetail | None = None
    conversation_memory: bool | None = None
    notifications_enabled: bool | None = None
    minimize_console_after_launch: bool | None = None
    assistant_name: str | None = Field(default=None, min_length=1, max_length=40)

    communication_mode: CommunicationMode | None = None
    voice_gender: VoiceGender | None = None
    voice_variant: str | None = Field(default=None, min_length=1, max_length=80)
    microphone_id: str | None = Field(default=None, min_length=1, max_length=300)
    random_conversations: bool | None = None

    unprepared_mission_action: UnpreparedMissionAction | None = None
    create_mission_backup: bool | None = None
    prepared_mission_suffix: str | None = Field(default=None, min_length=1, max_length=40)
    verify_mission_pack_before_launch: bool | None = None
    additional_mission_directories: list[str] | None = None

    default_installation_id: str | None = None
    default_profile_id: str | None = None


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
