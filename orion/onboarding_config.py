from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, Field

from orion.dcs_installations import DcsInstallationType
from orion.orion_settings import InterfaceLanguage


class VoiceLanguage(StrEnum):
    RU = "ru"
    EN = "en"
    AUTO = "auto"


class OrionBaseMode(StrEnum):
    AVIATION = "aviation"
    FREE = "free"
    HYBRID = "hybrid"


class OnboardingConfig(BaseModel):
    interface_language: InterfaceLanguage = InterfaceLanguage.RU
    preferred_dcs_type: DcsInstallationType = DcsInstallationType.AUTO
    voice_language: VoiceLanguage = VoiceLanguage.AUTO
    audio_output_id: str = Field(default="windows-default", min_length=1, max_length=300)
    prefer_vr_audio: bool = True
    base_mode: OrionBaseMode = OrionBaseMode.HYBRID
    completed: bool = False


class OnboardingConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_config_path()
        self._lock = RLock()

    def get(self) -> OnboardingConfig:
        with self._lock:
            if not self._path.is_file():
                return OnboardingConfig()
            try:
                return OnboardingConfig.model_validate_json(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return OnboardingConfig()

    def set(self, config: OnboardingConfig) -> OnboardingConfig:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(self._path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self._path)
            return config.model_copy(deep=True)

    def reset(self) -> OnboardingConfig:
        with self._lock:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass
            return OnboardingConfig()


def _default_config_path() -> Path:
    override = os.environ.get("ORION_CONFIG_DIR")
    if override:
        return Path(override) / "onboarding.json"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "ORION" / "onboarding.json"
    return Path.home() / ".orion" / "onboarding.json"


onboarding_config = OnboardingConfigStore()
