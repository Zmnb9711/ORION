from fastapi.testclient import TestClient

from orion.app import app


def test_pending_action_requires_explicit_decision() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/v1/pending-actions",
            json={
                "action_type": "laser_designation",
                "summary": "Designate target T-72-1 with laser",
                "payload": {"target_id": "T-72-1", "laser_code": 1688},
            },
        )
        action_id = created.json()["action_id"]
        listed = client.get("/v1/pending-actions", params={"status": "pending"})
        decided = client.post(
            f"/v1/pending-actions/{action_id}/decision",
            json={"confirm": True},
        )

    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    assert any(item["action_id"] == action_id for item in listed.json())
    assert decided.status_code == 200
    assert decided.json()["status"] == "confirmed"
    assert decided.json()["resolved_at"] is not None


def test_pending_action_cannot_be_resolved_twice() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/v1/pending-actions",
            json={"action_type": "smoke_mark", "summary": "Mark target with red smoke"},
        )
        action_id = created.json()["action_id"]
        first = client.post(
            f"/v1/pending-actions/{action_id}/decision",
            json={"confirm": False},
        )
        second = client.post(
            f"/v1/pending-actions/{action_id}/decision",
            json={"confirm": True},
        )

    assert first.status_code == 200
    assert first.json()["status"] == "rejected"
    assert second.status_code == 404
