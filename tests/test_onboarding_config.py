from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.onboarding_config import OnboardingConfig, OnboardingConfigStore


def test_onboarding_config_persists_user_choices(tmp_path: Path):
    store = OnboardingConfigStore(tmp_path / "onboarding.json")
    saved = store.set(OnboardingConfig(
        interface_language="ru",
        preferred_dcs_type="steam",
        voice_language="ru",
        audio_output_id="Pimax Dream Air Audio",
        prefer_vr_audio=True,
        base_mode="hybrid",
        completed=True,
    ))
    loaded = store.get()
    assert saved == loaded
    assert loaded.preferred_dcs_type.value == "steam"
    assert loaded.audio_output_id == "Pimax Dream Air Audio"
    assert loaded.completed is True


def test_onboarding_config_api_registered():
    client = TestClient(app)
    response = client.get("/v1/onboarding-config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["interface_language"] in {"ru", "en"}
    assert payload["preferred_dcs_type"] in {"auto", "steam", "standalone", "manual"}
    assert payload["base_mode"] in {"aviation", "free", "hybrid"}
