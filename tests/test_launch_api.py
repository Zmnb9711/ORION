from fastapi.testclient import TestClient

from orion.app import app

client = TestClient(app)


def test_create_and_preview_openxr_profile() -> None:
    response = client.post(
        "/v1/launch-profiles",
        json={
            "name": "Hornet OpenXR",
            "mode": "openxr",
            "dcs_executable": "C:/DCS World/bin-mt/DCS.exe",
            "mission_path": "C:/Missions/Test.miz",
        },
    )
    assert response.status_code == 201
    profile = response.json()

    plan_response = client.get(f"/v1/launch-profiles/{profile['profile_id']}/plan")
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["arguments"][:2] == ["--force_enable_VR", "--force_OpenXR"]
    assert plan["mission_path"].endswith("Test.miz")


def test_missing_launch_profile_returns_404() -> None:
    response = client.get("/v1/launch-profiles/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
