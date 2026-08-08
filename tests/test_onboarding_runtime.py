from fastapi.testclient import TestClient

from orion.app import app
from orion.onboarding_config import OnboardingConfig, OrionBaseMode, VoiceLanguage
from orion.onboarding_runtime import apply_onboarding_config
from orion.orion_settings import CommunicationMode, InterfaceLanguage, orion_settings
from orion.windows_audio_worker import windows_audio_worker


def test_apply_onboarding_updates_runtime_settings_and_audio():
    orion_settings.reset()
    windows_audio_worker.reset()
    state = apply_onboarding_config(
        OnboardingConfig(
            interface_language=InterfaceLanguage.EN,
            preferred_dcs_type="steam",
            voice_language=VoiceLanguage.EN,
            audio_output_id="pimax-dream-air",
            prefer_vr_audio=True,
            base_mode=OrionBaseMode.AVIATION,
        )
    )
    assert state.settings.interface_language == InterfaceLanguage.EN
    assert state.settings.communication_mode == CommunicationMode.AVIATION_ENGLISH
    assert state.settings.audio_output_id == "pimax-dream-air"
    assert state.dcs_discovery_mode.value == "steam"
    assert windows_audio_worker.devices()[0].device_id == "pimax-dream-air"


def test_free_mode_maps_to_free_communication():
    state = apply_onboarding_config(OnboardingConfig(base_mode=OrionBaseMode.FREE))
    assert state.settings.communication_mode == CommunicationMode.FREE_COMMUNICATION


def test_onboarding_runtime_api_registered(monkeypatch, tmp_path):
    from orion.onboarding_config import OnboardingConfigStore
    store = OnboardingConfigStore(tmp_path / "onboarding.json")
    store.set(OnboardingConfig(preferred_dcs_type="standalone", completed=True))
    monkeypatch.setattr("orion.onboarding_runtime.onboarding_config", store)

    client = TestClient(app)
    response = client.post("/v1/onboarding-runtime/apply")
    assert response.status_code == 200
    payload = response.json()
    assert payload["dcs_discovery_mode"] == "standalone"
    assert payload["config"]["completed"] is True
