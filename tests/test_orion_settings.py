from fastapi.testclient import TestClient

from orion.app import app
from orion.orion_settings import OrionSettingsStore, OrionSettingsUpdate, ResponseDetail


def test_settings_store_updates_only_orion_behavior() -> None:
    store = OrionSettingsStore()
    updated = store.update(
        OrionSettingsUpdate(
            response_detail=ResponseDetail.BRIEF,
            minimize_console_after_launch=True,
            assistant_name="Wingman",
        )
    )

    assert updated.response_detail is ResponseDetail.BRIEF
    assert updated.minimize_console_after_launch is True
    assert updated.assistant_name == "Wingman"
    assert not hasattr(updated, "vr_resolution")
    assert not hasattr(updated, "openxr_runtime")
    assert not hasattr(updated, "dcs_graphics")


def test_settings_api_routes_are_available() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]

    assert "/v1/settings" in paths
    assert "/v1/settings/reset" in paths
