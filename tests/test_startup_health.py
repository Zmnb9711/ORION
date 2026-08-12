import json
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


def test_launcher_startup_health_queries_core(monkeypatch):
    monkeypatch.setenv("ORION_PROCESS_ROLE", "launcher")
    monkeypatch.setenv("ORION_CORE_BASE_URL", "http://127.0.0.1:8123")
    seen: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "state": "degraded",
                    "checks": [
                        {
                            "key": "telemetry",
                            "passed": True,
                            "blocking": False,
                            "message": "Live DCS telemetry is connected",
                            "recovery_action": None,
                        }
                    ],
                    "telemetry_connected": True,
                    "recovery_actions": [],
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("orion.startup_health.urllib.request.urlopen", fake_urlopen)

    report = inspect_startup_health()

    assert seen == {
        "url": "http://127.0.0.1:8123/v1/startup-health",
        "method": "GET",
        "timeout": 2.0,
    }
    assert report.telemetry_connected is True
    assert report.checks[0].key == "telemetry"
    assert report.checks[0].passed is True


def test_startup_health_api_registered():
    client = TestClient(app)
    response = client.get("/v1/startup-health")
    assert response.status_code == 200
    assert "state" in response.json()
