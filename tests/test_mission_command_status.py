from uuid import uuid4

from fastapi.testclient import TestClient

from orion.app import app
from orion.capabilities import MissionCapability, MissionPackRegistration, capability_registry
from orion.mission_command_status import MissionCommandStatus


client = TestClient(app)


def test_mission_command_lifecycle(monkeypatch) -> None:
    capability_registry.register(
        MissionPackRegistration(
            mission_id="test-mission",
            pack_version="0.1.0",
            protocol_version="0.2",
            capabilities=[MissionCapability.SMOKE],
        )
    )

    monkeypatch.setattr("socket.socket.sendto", lambda self, payload, address: len(payload))

    command_id = uuid4()
    response = client.post(
        "/v1/mission-bridge/commands",
        json={
            "command_id": str(command_id),
            "command": "smoke",
            "target_unit_id": "Target-1",
            "smoke_color": "red",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"

    status = client.get(f"/v1/mission-bridge/commands/{command_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"

    completed = client.put(
        f"/v1/mission-bridge/commands/{command_id}/status",
        json={
            "command_id": str(command_id),
            "status": MissionCommandStatus.COMPLETED.value,
            "message": "Smoke marker created",
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["message"] == "Smoke marker created"


def test_status_update_rejects_mismatched_id() -> None:
    command_id = uuid4()
    response = client.put(
        f"/v1/mission-bridge/commands/{command_id}/status",
        json={
            "command_id": str(uuid4()),
            "status": "failed",
            "message": "Wrong command",
        },
    )
    assert response.status_code == 400
