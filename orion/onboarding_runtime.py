from __future__ import annotations

from pydantic import BaseModel

from orion.dcs_installations import DcsInstallationType
from orion.onboarding_config import OnboardingConfig, OrionBaseMode, VoiceLanguage, onboarding_config
from orion.orion_settings import CommunicationMode, InterfaceLanguage, OrionSettings, OrionSettingsUpdate, orion_settings
from orion.windows_audio_worker import AudioDevice, windows_audio_worker


class OnboardingRuntimeState(BaseModel):
    config: OnboardingConfig
    settings: OrionSettings
    dcs_discovery_mode: DcsInstallationType
    audio_output_id: str
    prefer_vr_audio: bool


def _communication_mode(config: OnboardingConfig) -> CommunicationMode:
    if config.base_mode is OrionBaseMode.FREE:
        return CommunicationMode.FREE_COMMUNICATION
    if config.voice_language is VoiceLanguage.EN:
        return CommunicationMode.AVIATION_ENGLISH
    if config.voice_language is VoiceLanguage.RU:
        return CommunicationMode.AVIATION_RUSSIAN
    return (
        CommunicationMode.AVIATION_RUSSIAN
        if config.interface_language is InterfaceLanguage.RU
        else CommunicationMode.AVIATION_ENGLISH
    )


def apply_onboarding_config(config: OnboardingConfig | None = None) -> OnboardingRuntimeState:
    selected = config or onboarding_config.get()
    settings = orion_settings.update(
        OrionSettingsUpdate(
            interface_language=selected.interface_language,
            communication_mode=_communication_mode(selected),
            audio_output_id=selected.audio_output_id,
        )
    )
    windows_audio_worker.select_device(
        AudioDevice(
            device_id=selected.audio_output_id,
            name=("Preferred VR audio output" if selected.prefer_vr_audio else "Configured audio output"),
            is_default=selected.audio_output_id in {"default", "windows-default"},
        )
    )
    return OnboardingRuntimeState(
        config=selected,
        settings=settings,
        dcs_discovery_mode=selected.preferred_dcs_type,
        audio_output_id=selected.audio_output_id,
        prefer_vr_audio=selected.prefer_vr_audio,
    )


def current_onboarding_runtime() -> OnboardingRuntimeState:
    return apply_onboarding_config(onboarding_config.get())
