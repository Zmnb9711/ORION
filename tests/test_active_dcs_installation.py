from pathlib import Path

from fastapi.testclient import TestClient

from orion.active_dcs_installation import ActiveDcsInstallation, ActiveDcsInstallationStore
from orion.app import app


def test_active_installation_persists_to_disk(tmp_path: Path):
    store = ActiveDcsInstallationStore(tmp_path / "active-dcs.json")
    selection = ActiveDcsInstallation(
        installation_type="steam",
        executable_path=r"D:\SteamLibrary\steamapps\common\DCSWorld\bin\DCS.exe",
        install_root=r"D:\SteamLibrary\steamapps\common\DCSWorld",
        saved_games_path=r"C:\Users\Pilot\Saved Games\DCS",
        display_name="DCS Steam",
    )
    store.set(selection)
    reloaded = ActiveDcsInstallationStore(tmp_path / "active-dcs.json").get()
    assert reloaded == selection


def test_active_installation_api_is_registered(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ORION_CONFIG_DIR", str(tmp_path))
    client = TestClient(app)
    payload = {
        "installation_type": "standalone",
        "executable_path": r"C:\Program Files\Eagle Dynamics\DCS World\bin\DCS.exe",
        "install_root": r"C:\Program Files\Eagle Dynamics\DCS World",
        "saved_games_path": r"C:\Users\Pilot\Saved Games\DCS",
        "display_name": "DCS Standalone",
    }
    response = client.put("/v1/dcs-active", json=payload)
    assert response.status_code == 200
    assert response.json()["installation_type"] == "standalone"
