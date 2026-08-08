from pathlib import Path

from orion.onboarding_config import OnboardingConfig, OnboardingConfigStore, OrionBaseMode, VoiceLanguage
from orion.orion_settings import CommunicationMode, InterfaceLanguage, orion_settings
from orion.startup_onboarding import apply_completed_onboarding_at_startup


def test_incomplete_onboarding_is_not_applied(tmp_path: Path, monkeypatch):
    store = OnboardingConfigStore(tmp_path / "onboarding.json")
    store.set(OnboardingConfig(interface_language=InterfaceLanguage.EN, completed=False))
    monkeypatch.setattr("orion.startup_onboarding.onboarding_config", store)

    orion_settings.reset()
    result = apply_completed_onboarding_at_startup()

    assert result.applied is False
    assert orion_settings.get().interface_language == InterfaceLanguage.RU


def test_completed_onboarding_is_applied_at_startup(tmp_path: Path, monkeypatch):
    store = OnboardingConfigStore(tmp_path / "onboarding.json")
    store.set(
        OnboardingConfig(
            interface_language=InterfaceLanguage.EN,
            voice_language=VoiceLanguage.EN,
            base_mode=OrionBaseMode.AVIATION,
            audio_output_id="vr-headset",
            completed=True,
        )
    )
    monkeypatch.setattr("orion.startup_onboarding.onboarding_config", store)

    orion_settings.reset()
    result = apply_completed_onboarding_at_startup()

    assert result.applied is True
    assert result.runtime is not None
    assert result.runtime.audio_output_id == "vr-headset"
    settings = orion_settings.get()
    assert settings.interface_language == InterfaceLanguage.EN
    assert settings.communication_mode == CommunicationMode.AVIATION_ENGLISH
