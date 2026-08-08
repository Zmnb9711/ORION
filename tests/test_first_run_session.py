from pathlib import Path

from fastapi.testclient import TestClient

from orion.active_dcs_installation import ActiveDcsInstallation, ActiveDcsInstallationStore
from orion.app import app
from orion.dcs_installations import DcsInstallationType
from orion.first_run_session import FirstRunSessionStep, get_first_run_session


def test_session_api_registered():
    response = TestClient(app).get("/v1/first-run/session?mode=manual")
    assert response.status_code == 200
    assert response.json()["step"] in {"detect", "select_active", "install_integration", "test_connection", "ready"}


def test_session_requires_integration_after_active_selection(tmp_path: Path, monkeypatch):
    dcs = tmp_path / "DCSWorld" / "bin" / "DCS.exe"
    dcs.parent.mkdir(parents=True)
    dcs.write_bytes(b"")
    saved = tmp_path / "Saved Games" / "DCS"
    saved.mkdir(parents=True)

    store = ActiveDcsInstallationStore(tmp_path / "active.json")
    store.set(ActiveDcsInstallation(
        installation_type=DcsInstallationType.STEAM,
        executable_path=str(dcs),
        install_root=str(dcs.parents[1]),
        saved_games_path=str(saved),
        display_name="DCS Steam",
    ))
    monkeypatch.setattr("orion.first_run_session.active_dcs_installation", store)
    monkeypatch.setattr("orion.first_run_session.discover_dcs_installations", lambda mode: type("Discovery", (), {"candidates": []})())
    monkeypatch.setattr("orion.first_run_session.telemetry_handshake.snapshot", lambda: type("Live", (), {"connected": False, "aircraft_type": None})())

    state = get_first_run_session(DcsInstallationType.STEAM)
    assert state.step == FirstRunSessionStep.INSTALL_INTEGRATION
    assert state.progress_percent == 50
    assert state.next_action == "install_integration"
