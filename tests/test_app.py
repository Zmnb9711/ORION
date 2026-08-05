from fastapi.testclient import TestClient

from orion.app import app


def sample_payload() -> dict:
    return {
        "protocol_version": "0.1",
        "source": "test",
        "state": {
            "aircraft_type": "FA-18C_hornet",
            "callsign": "Enfield 1-1",
            "position": {
                "latitude": 41.6103,
                "longitude": 41.5997,
                "altitude_m": 2500,
            },
            "heading_deg": 90,
            "true_airspeed_mps": 210,
            "vertical_speed_mps": 0,
            "fuel_fraction": 0.72,
        },
    }


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ingest_and_read_latest_telemetry() -> None:
    with TestClient(app) as client:
        accepted = client.post("/v1/telemetry", json=sample_payload())
        latest = client.get("/v1/telemetry/latest")

    assert accepted.status_code == 202
    assert accepted.json()["aircraft_type"] == "FA-18C_hornet"
    assert latest.status_code == 200
    assert latest.json()["state"]["callsign"] == "Enfield 1-1"


def test_allowed_command_is_sent() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/commands",
            json={"command": "show_message", "message": "ORION online"},
        )
    assert response.status_code == 202
    assert response.json() == {"status": "sent", "command": "show_message"}


def test_unknown_command_is_rejected() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/commands", json={"command": "spawn_unit"})
    assert response.status_code == 422
