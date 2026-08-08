from uuid import uuid4

from fastapi.testclient import TestClient

from orion.app import app
from orion.dcs_process import DcsProcessManager
from orion.launch_profiles import DcsLaunchProfileCreate, LaunchProfileStore
from orion.recovery_launch import RecoveryLaunchState, start_dcs_for_recovery


class FakeHandle:
    pid = 4242

    def poll(self):
        return None


def test_recovery_launch_requires_profile(monkeypatch):
    store = LaunchProfileStore()
    monkeypatch.setattr("orion.recovery_launch.launch_profiles", store)
    result = start_dcs_for_recovery()
    assert result.state == RecoveryLaunchState.SELECTION_REQUIRED


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
