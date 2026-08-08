from fastapi.testclient import TestClient

from orion.app import app


def test_mission_control_query_api_is_registered():
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/mission-control/query" in paths
