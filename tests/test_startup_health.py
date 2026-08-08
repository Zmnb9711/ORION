from pathlib import Path

from fastapi.testclient import TestClient

from orion.active_dcs_installation import ActiveDcsInstallation, ActiveDcsInstallationStore
from orion.app import app
from orion.dcs_installations import DcsInstallationType
from orion.onboarding_config import OnboardingConfig, OnboardingConfigStore
from orion.startup_health import RecoveryAction, StartupHealthState, inspect_startup_health
from orion.windows_wasapi_backend import WasapiEndpoint, WasapiEndpointCatalog


def test_startup_health_requires_dcs_reselection_when_active_missing(tmp_path: Path, monkeypatch):
    active_store = ActiveDcsInstallationStore(tmp_path / "active.json")
    onboarding_store = OnboardingConfigStore(tmp_path / "onboarding.json")
    onboarding_store.set(OnboardingConfig(completed=True))
    monkeypatch.setattr("orion.startup_health.active_dcs_installation", active_store)
    monkeypatch.setattr("orion.startup_health.onboarding_config", onboarding_store)

    report = inspect_startup_health()
    assert report.state == StartupHealthState.ACTION_REQUIRED
    assert RecoveryAction.RESELECT_DCS in report.recovery_actions


def test_startup_health_detects_export_repair_and_missing_audio(tmp_path: Path, monkeypatch):
    dcs = tmp_path / "DCSWorld" / "bin" / "DCS.exe"
    dcs.parent.mkdir(parents=True)
    dcs.write_bytes(b"")
    saved = tmp_path / "Saved Games" / "DCS"
    saved.mkdir(parents=True)

    active_store = ActiveDcsInstallationStore(tmp_path / "active.json")
    active_store.set(ActiveDcsInstallation(
        installation_type=DcsInstallationType.STEAM,
        executable_path=str(dcs),
        install_root=str(dcs.parents[1]),
        saved_games_path=str(saved),
        display_name="DCS Steam",
    ))
    onboarding_store = OnboardingConfigStore(tmp_path / "onboarding.json")
    onboarding_store.set(OnboardingConfig(audio_output_id="missing-vr", completed=True))
    catalog = WasapiEndpointCatalog(provider=lambda: [WasapiEndpoint(device_id="other", name="Speakers")])

    monkeypatch.setattr("orion.startup_health.active_dcs_installation", active_store)
    monkeypatch.setattr("orion.startup_health.onboarding_config", onboarding_store)
    monkeypatch.setattr("orion.startup_health.wasapi_endpoint_catalog", catalog)

    report = inspect_startup_health()
    assert RecoveryAction.REPAIR_INTEGRATION in report.recovery_actions
    assert RecoveryAction.RESELECT_AUDIO in report.recovery_actions
    assert report.state == StartupHealthState.ACTION_REQUIRED


def test_startup_health_api_registered():
    client = TestClient(app)
    response = client.get("/v1/startup-health")
    assert response.status_code == 200
    assert "state" in response.json()
