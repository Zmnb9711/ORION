from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import orion.communication_profile_api as profile_api
from orion.communication_contracts import CommunicationProfileId
from orion.communication_profile_packs import CommunicationProfileService, CommunicationProfileStore


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, CommunicationProfileService]:  # noqa: ANN001
    service = CommunicationProfileService(CommunicationProfileStore(tmp_path / "profiles"))
    monkeypatch.setattr(profile_api, "communication_profile_service", lambda: service)
    app = FastAPI()
    app.include_router(profile_api.router)
    return TestClient(app), service


def test_launcher_to_core_selection_propagates_and_persists(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    client, service = _client(tmp_path, monkeypatch)
    initial = client.get("/v1/communication-profiles")
    assert initial.status_code == 200
    assert initial.json()["configured_profile_id"] is None
    assert initial.json()["effective_profile_id"] is None
    assert len(initial.json()["profiles"]) == 4

    selected = client.put(
        "/v1/communication-profiles/selection", json={"profile_id": "FAA_US"}
    )
    assert selected.status_code == 200
    assert selected.json()["configured_profile_id"] == "FAA_US"
    assert selected.json()["effective_profile_id"] is None
    assert selected.json()["configured_pack_version"] == "0.1.0"
    assert selected.json()["effective_pack_version"] is None
    assert [item["profile_id"] for item in selected.json()["profiles"] if item["selected"]] == [
        "FAA_US"
    ]

    reloaded = CommunicationProfileService(CommunicationProfileStore(service.store.root))
    assert reloaded.get_selected_profile() is CommunicationProfileId.FAA_US


def test_api_rejects_unknown_profile_and_unknown_payload_fields(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    client, _ = _client(tmp_path, monkeypatch)
    assert client.put(
        "/v1/communication-profiles/selection", json={"profile_id": "UNKNOWN"}
    ).status_code == 422
    assert client.put(
        "/v1/communication-profiles/selection",
        json={"profile_id": "ICAO", "response_language": "ru-RU"},
    ).status_code == 422


def test_details_separate_source_content_and_runtime_status(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    client, _ = _client(tmp_path, monkeypatch)
    details = client.get("/v1/communication-profiles/ICAO/details")
    assert details.status_code == 200
    payload = details.json()
    assert payload["source_registry_status"] == "PARTIAL"
    assert payload["pack"]["verification"] == "PARTIAL"
    assert payload["pack"]["readiness"] == "RESEARCH_ONLY"
    assert payload["pack"]["language_realizations"] == []


def test_update_source_not_configured_is_truthful_and_non_mutating(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    client, service = _client(tmp_path, monkeypatch)
    before = service.get_active_pack(CommunicationProfileId.FAA_US)
    check = client.post("/v1/communication-profiles/FAA_US/check-updates")
    assert check.status_code == 200
    assert check.json()["check"]["state"] == "NO_REGISTRY"
    update = client.post("/v1/communication-profiles/FAA_US/update")
    assert update.status_code == 409
    assert update.json()["detail"]["code"] == "UPDATE_NOT_AVAILABLE"
    after = service.get_active_pack(CommunicationProfileId.FAA_US)
    assert before is not None and after is not None
    assert before.manifest.content_hash == after.manifest.content_hash


def test_profile_router_is_registered_in_packaged_core_app() -> None:
    from orion.app import app

    paths = app.openapi()["paths"]
    assert "/v1/communication-profiles" in paths
    assert "/v1/communication-profiles/selection" in paths
    assert "/v1/communication-profiles/{profile_id}/check-updates" in paths
    assert "/v1/communication-profiles/{profile_id}/update" in paths
    assert "/v1/communication-profiles/{profile_id}/rollback" in paths
