import json
from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.dcs_installation_discovery import DcsDiscoveryCandidate, DcsDiscoveryResult
from orion.dcs_installations import DcsInstallationType
from orion.first_run_actions import FirstRunAction, FirstRunActionResult


def test_first_run_action_routes_registered():
    client = TestClient(app)
    response = client.post("/v1/first-run/actions/detect?mode=manual")
    assert response.status_code == 200
    assert response.json()["action"] == "detect"


def test_detect_result_exposes_candidates_to_desktop_ui():
    candidate = DcsDiscoveryCandidate(
        installation_type=DcsInstallationType.STEAM,
        name="DCS Steam",
        install_root=r"D:\SteamLibrary\steamapps\common\DCSWorld",
        executable_path=r"D:\SteamLibrary\steamapps\common\DCSWorld\bin\DCS.exe",
        exists=True,
        source_detail=r"D:\SteamLibrary",
    )
    result = FirstRunActionResult(
        action=FirstRunAction.DETECT,
        ok=True,
        message="Found 1 DCS installation(s)",
        discovery=DcsDiscoveryResult(mode=DcsInstallationType.AUTO, candidates=[candidate]),
        next_actions=[FirstRunAction.SELECT_ACTIVE],
    )

    assert result.candidates == [candidate]
    assert result.candidates[0].install_root.endswith("DCSWorld")


def test_detect_result_without_discovery_exposes_empty_candidates():
    result = FirstRunActionResult(action=FirstRunAction.DETECT, ok=False, message="No DCS installations found")
    assert result.candidates == []


def test_launcher_telemetry_check_queries_core(monkeypatch):
    from orion.first_run_actions import test_live_connection

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
                    "action": "test_connection",
                    "ok": True,
                    "message": "Live DCS telemetry received",
                    "telemetry_connected": True,
                    "aircraft_type": "FA-18C_hornet",
                    "next_actions": [],
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("orion.first_run_actions.urllib.request.urlopen", fake_urlopen)

    result = test_live_connection()

    assert seen == {
        "url": "http://127.0.0.1:8123/v1/first-run/actions/test-connection",
        "method": "POST",
        "timeout": 2.0,
    }
    assert result.ok is True
    assert result.telemetry_connected is True
    assert result.aircraft_type == "FA-18C_hornet"


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
