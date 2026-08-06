from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orion.mission_preparation_api import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _make_miz(path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("mission", "mission = {}")
        archive.writestr("options", "options = {}")


def test_prepare_and_inspect_api(tmp_path) -> None:
    source = tmp_path / "Training.miz"
    pack = tmp_path / "ORION_MissionPack.lua"
    _make_miz(source)
    pack.write_text("ORION = {}", encoding="utf-8")

    client = _client()
    response = client.post(
        "/v1/mission-manager/prepare",
        json={
            "source_mission": str(source),
            "mission_pack_script": str(pack),
        },
    )

    assert response.status_code == 201
    prepared = response.json()["prepared_mission"]
    assert response.json()["inspection"]["activation_status"] == "embedded_only"

    inspection = client.post(
        "/v1/mission-manager/inspect",
        params={"mission_path": prepared},
    )
    assert inspection.status_code == 200
    assert inspection.json()["mission_pack_present"] is True


def test_prepare_api_rejects_missing_source(tmp_path) -> None:
    pack = tmp_path / "ORION_MissionPack.lua"
    pack.write_text("ORION = {}", encoding="utf-8")

    response = _client().post(
        "/v1/mission-manager/prepare",
        json={
            "source_mission": str(tmp_path / "Missing.miz"),
            "mission_pack_script": str(pack),
        },
    )

    assert response.status_code == 404
