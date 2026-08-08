from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.dcs_installation_discovery import discover_dcs_installations
from orion.dcs_installations import DcsInstallationType


def test_auto_mode_returns_steam_and_standalone_candidates(tmp_path: Path):
    steam_root = tmp_path / "Steam"
    steamapps = steam_root / "steamapps"
    steam_dcs = steamapps / "common" / "DCSWorld"
    (steam_dcs / "bin").mkdir(parents=True)
    (steam_dcs / "bin" / "DCS.exe").write_bytes(b"")
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / "appmanifest_223750.acf").write_text('"AppState" { "installdir" "DCSWorld" }', encoding="utf-8")

    standalone = tmp_path / "Eagle Dynamics" / "DCS World"
    (standalone / "bin").mkdir(parents=True)
    (standalone / "bin" / "DCS.exe").write_bytes(b"")

    result = discover_dcs_installations(
        DcsInstallationType.AUTO,
        steam_roots=[steam_root],
        standalone_roots=[standalone],
    )

    assert {item.installation_type for item in result.candidates} == {
        DcsInstallationType.STEAM,
        DcsInstallationType.STANDALONE,
    }


def test_explicit_mode_filters_other_installation_type(tmp_path: Path):
    standalone = tmp_path / "DCS World"
    (standalone / "bin").mkdir(parents=True)
    (standalone / "bin" / "DCS.exe").write_bytes(b"")

    result = discover_dcs_installations(
        DcsInstallationType.STANDALONE,
        steam_roots=[],
        standalone_roots=[standalone],
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].installation_type == DcsInstallationType.STANDALONE


def test_discovery_api_is_registered():
    client = TestClient(app)
    response = client.get("/v1/dcs-discovery", params={"mode": "manual"})
    assert response.status_code == 200
    assert response.json()["mode"] == "manual"
    assert response.json()["candidates"] == []
