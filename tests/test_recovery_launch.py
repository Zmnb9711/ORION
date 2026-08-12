import json
from uuid import uuid4

from fastapi.testclient import TestClient

from orion.active_dcs_installation import ActiveDcsInstallation, ActiveDcsInstallationStore
from orion.app import app
from orion.dcs_installations import DcsInstallationType
from orion.dcs_process import DcsProcessManager
from orion.launch_profiles import DcsLaunchProfileCreate, LaunchProfileStore
from orion.recovery_launch import RecoveryLaunchState, start_dcs_for_recovery


class FakeHandle:
    pid = 4242

    def poll(self):
        return None


def test_recovery_launch_requires_active_dcs_or_profile(monkeypatch, tmp_path):
    store = LaunchProfileStore()
    active = ActiveDcsInstallationStore(tmp_path / "active.json")
    monkeypatch.setattr("orion.recovery_launch.launch_profiles", store)
    monkeypatch.setattr("orion.launch_profiles.active_dcs_installation", active)
    result = start_dcs_for_recovery()
    assert result.state == RecoveryLaunchState.SELECTION_REQUIRED
    assert "complete DCS Setup" in result.message


def test_recovery_launch_creates_default_profile_from_active_dcs(monkeypatch, tmp_path):
    dcs = tmp_path / "DCSWorld" / "bin-mt" / "DCS.exe"
    dcs.parent.mkdir(parents=True)
    dcs.write_bytes(b"")
    active = ActiveDcsInstallationStore(tmp_path / "active.json")
    active.set(
        ActiveDcsInstallation(
            installation_type=DcsInstallationType.STEAM,
            executable_path=str(dcs),
            install_root=str(dcs.parents[1]),
            saved_games_path=str(tmp_path / "Saved Games" / "DCS"),
            display_name="DCS Steam",
        )
    )
    store = LaunchProfileStore()
    process_manager = DcsProcessManager(launcher=lambda plan: FakeHandle())
    monkeypatch.setattr("orion.launch_profiles.active_dcs_installation", active)
    monkeypatch.setattr("orion.recovery_launch.launch_profiles", store)
    monkeypatch.setattr("orion.recovery_launch.dcs_processes", process_manager)
    monkeypatch.setattr("orion.recovery_launch.telemetry_handshake.snapshot", lambda: type("Live", (), {"connected": False, "aircraft_type": None})())

    result = start_dcs_for_recovery()
    assert result.state == RecoveryLaunchState.WAITING_FOR_TELEMETRY
    assert result.pid == 4242
    profiles = store.list()
    assert len(profiles) == 1
    assert result.profile_id == profiles[0].profile_id
    assert profiles[0].name == "Active DCS"


def test_recovery_launch_uses_only_profile(monkeypatch, tmp_path):
    dcs = tmp_path / "DCS.exe"
    dcs.write_bytes(b"")
    store = LaunchProfileStore()
    profile = store.create(DcsLaunchProfileCreate(name="Steam VR", dcs_executable=str(dcs), use_active_installation=False))
    process_manager = DcsProcessManager(launcher=lambda plan: FakeHandle())
    monkeypatch.setattr("orion.recovery_launch.launch_profiles", store)
    monkeypatch.setattr("orion.recovery_launch.dcs_processes", process_manager)
    monkeypatch.setattr("orion.recovery_launch.telemetry_handshake.snapshot", lambda: type("Live", (), {"connected": False, "aircraft_type": None})())

    result = start_dcs_for_recovery()
    assert result.state == RecoveryLaunchState.WAITING_FOR_TELEMETRY
    assert result.profile_id == profile.profile_id
    assert result.pid == 4242


def test_launcher_recovery_launch_queries_core(monkeypatch):
    monkeypatch.setenv("ORION_PROCESS_ROLE", "launcher")
    monkeypatch.setenv("ORION_CORE_BASE_URL", "http://127.0.0.1:8123")
    launch_id = uuid4()
    profile_id = uuid4()
    seen: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "state": "waiting_for_telemetry",
                    "message": "DCS launched; waiting for live telemetry",
                    "profile_id": str(profile_id),
                    "launch_id": str(launch_id),
                    "pid": 4242,
                    "telemetry_connected": False,
                    "aircraft_type": None,
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("orion.recovery_launch.urllib.request.urlopen", fake_urlopen)

    result = start_dcs_for_recovery()

    assert seen == {
        "url": "http://127.0.0.1:8123/v1/recovery-launch/start",
        "method": "POST",
        "timeout": 3.0,
    }
    assert result.state == RecoveryLaunchState.WAITING_FOR_TELEMETRY
    assert result.pid == 4242
    assert result.launch_id == launch_id
    assert result.profile_id == profile_id


def test_recovery_launch_api_registered():
    client = TestClient(app)
    response = client.get("/v1/recovery-launch/status")
    assert response.status_code == 200
    assert response.json()["state"] in {"waiting_for_telemetry", "connected"}
