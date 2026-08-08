from pathlib import Path

from fastapi.testclient import TestClient

from orion.active_dcs_installation import ActiveDcsInstallation, ActiveDcsInstallationStore
from orion.app import app
from orion.dcs_installations import DcsInstallationType
from orion.onboarding_config import OnboardingConfig, OnboardingConfigStore
from orion.recovery_orchestrator import run_recovery
from orion.startup_health import RecoveryAction
from orion.windows_wasapi_backend import WasapiEndpoint, WasapiEndpointCatalog


def test_repair_integration_recovers_export_lua(tmp_path: Path, monkeypatch):
    dcs = tmp_path / "DCSWorld" / "bin" / "DCS.exe"
    dcs.parent.mkdir(parents=True)
    dcs.write_bytes(b"")
    saved = tmp_path / "Saved Games" / "DCS"
    saved.mkdir(parents=True)

    active = ActiveDcsInstallationStore(tmp_path / "active.json")
    active.set(ActiveDcsInstallation(
        installation_type=DcsInstallationType.STEAM,
        executable_path=str(dcs),
        install_root=str(dcs.parents[1]),
        saved_games_path=str(saved),
        display_name="DCS Steam",
    ))
    config = OnboardingConfigStore(tmp_path / "onboarding.json")
    config.set(OnboardingConfig(completed=True))

    monkeypatch.setattr("orion.recovery_orchestrator.active_dcs_installation", active)
    monkeypatch.setattr("orion.recovery_orchestrator.onboarding_config", config)
    monkeypatch.setattr("orion.startup_health.active_dcs_installation", active)
    monkeypatch.setattr("orion.startup_health.onboarding_config", config)

    result = run_recovery(RecoveryAction.REPAIR_INTEGRATION)
    assert result.ok is True
    assert (saved / "Scripts" / "Export.lua").is_file()


def test_audio_recovery_prefers_vr_candidate(tmp_path: Path, monkeypatch):
    config = OnboardingConfigStore(tmp_path / "onboarding.json")
    config.set(OnboardingConfig(audio_output_id="missing-device", prefer_vr_audio=True, completed=True))
    catalog = WasapiEndpointCatalog(lambda: [
        WasapiEndpoint(device_id="pimax", name="Pimax Dream Air Audio", active=True),
        WasapiEndpoint(device_id="realtek", name="Speakers Realtek", active=True),
    ])
    monkeypatch.setattr("orion.recovery_orchestrator.onboarding_config", config)
    monkeypatch.setattr("orion.recovery_orchestrator.wasapi_endpoint_catalog", catalog)
    monkeypatch.setattr("orion.startup_health.onboarding_config", config)
    monkeypatch.setattr("orion.startup_health.wasapi_endpoint_catalog", catalog)

    result = run_recovery(RecoveryAction.RESELECT_AUDIO)
    assert result.ok is True
    assert result.config is not None
    assert result.config.audio_output_id == "pimax"


def test_recovery_route_registered():
    client = TestClient(app)
    response = client.post("/v1/recovery/start_dcs")
    assert response.status_code == 200
    assert response.json()["action"] == "start_dcs"
