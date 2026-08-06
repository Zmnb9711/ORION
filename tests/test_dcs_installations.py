from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.dcs_installations import DcsInstallationCreate, dcs_installations


def test_manual_dcs_installation_accepts_windows_path() -> None:
    item = dcs_installations.create(
        DcsInstallationCreate(
            name="Custom DCS",
            executable_path=r"E:\Games\DCS World\bin-mt\DCS.exe",
        )
    )
    assert item.name == "Custom DCS"
    assert item.exists is False


def test_manual_dcs_installation_api(tmp_path: Path) -> None:
    executable = tmp_path / "DCS.exe"
    executable.write_bytes(b"")

    with TestClient(app) as client:
        response = client.post(
            "/v1/dcs-installations",
            json={
                "name": "Portable DCS",
                "executable_path": str(executable),
                "source": "manual",
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["exists"] is True

        listed = client.get("/v1/dcs-installations")
        assert listed.status_code == 200
        assert any(item["installation_id"] == payload["installation_id"] for item in listed.json())

        refreshed = client.post(
            f"/v1/dcs-installations/{payload['installation_id']}/refresh"
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["exists"] is True
