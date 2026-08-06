from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app

client = TestClient(app)


def test_mission_manager_discovers_custom_missions(tmp_path: Path) -> None:
    custom = tmp_path / "missions"
    custom.mkdir()
    (custom / "VR Training.miz").write_bytes(b"mission")

    response = client.post(
        "/v1/mission-manager/discover",
        json={
            "saved_games_path": str(tmp_path / "saved-games"),
            "custom_directories": [str(custom)],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "VR Training"
    assert payload[0]["source"] == "custom"
