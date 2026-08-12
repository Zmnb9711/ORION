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


def test_recovery_launch_api_registered():
    client = TestClient(app)
    response = client.get("/v1/recovery-launch/status")
    assert response.status_code == 200
    assert response.json()["state"] in {"waiting_for_telemetry", "connected"}
