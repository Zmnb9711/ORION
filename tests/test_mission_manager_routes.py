from fastapi.testclient import TestClient

from orion.app import app


client = TestClient(app)


def test_mission_manager_routes_are_registered() -> None:
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]

    assert "/v1/mission-manager/discover" in paths
    assert "/v1/mission-manager/prepare" in paths
    assert "/v1/mission-manager/inspect" in paths
    assert "/v1/mission-manager/activation-plan" in paths
    assert "/v1/mission-manager/activate" in paths
