from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.first_run_actions import FirstRunAction


def test_first_run_action_routes_registered():
    client = TestClient(app)
    response = client.post("/v1/first-run/actions/detect?mode=manual")
    assert response.status_code == 200
    assert response.json()["action"] == "detect"


def test_select_active_action_returns_next_steps(tmp_path: Path, monkeypatch):
    dcs = tmp_path / "DCSWorld" / "bin" / "DCS.exe"
    dcs.parent.mkdir(parents=True)
    dcs.write_bytes(b"")
    saved = tmp_path / "Saved Games" / "DCS"
    saved.mkdir(parents=True)

    from orion.active_dcs_installation import ActiveDcsInstallationStore
    store = ActiveDcsInstallationStore(tmp_path / "active.json")
    monkeypatch.setattr("orion.first_run_actions.active_dcs_installation", store)

    client = TestClient(app)
    response = client.post(
        "/v1/first-run/actions/select-active",
        json={
            "installation_type": "steam",
            "executable_path": str(dcs),
            "install_root": str(dcs.parents[1]),
            "saved_games_path": str(saved),
            "display_name": "DCS Steam",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["active"]["installation_type"] == "steam"
    assert "install_integration" in payload["next_actions"]
    assert "test_connection" in payload["next_actions"]


def test_install_integration_requires_saved_games(monkeypatch, tmp_path: Path):
    from orion.active_dcs_installation import ActiveDcsInstallationStore
    store = ActiveDcsInstallationStore(tmp_path / "active.json")
    monkeypatch.setattr("orion.first_run_actions.active_dcs_installation", store)

    from orion.first_run_actions import install_active_integration
    result = install_active_integration()
    assert result.ok is False
    assert result.action == FirstRunAction.INSTALL_INTEGRATION
    assert result.next_actions == [FirstRunAction.SELECT_ACTIVE]
