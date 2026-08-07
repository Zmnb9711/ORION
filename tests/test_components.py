from fastapi.testclient import TestClient

from orion.app import app
from orion.components import InstallPreset, component_registry


def test_recommended_plan_resolves_dependencies_and_size() -> None:
    plan = component_registry.plan(InstallPreset.RECOMMENDED)
    assert plan.resolved == ["orion-core", "dcs-integration", "aircraft-fa18c", "online-voice"]
    assert plan.download_size_mb == 60
    assert plan.installed_size_mb == 215


def test_custom_plan_adds_required_dependencies() -> None:
    plan = component_registry.plan(InstallPreset.CUSTOM, requested=["manual-fa18c"])
    assert plan.resolved == ["orion-core", "dcs-integration", "aircraft-fa18c", "manual-fa18c"]


def test_full_offline_plan_contains_optional_local_models() -> None:
    plan = component_registry.plan(InstallPreset.FULL_OFFLINE)
    assert "offline-stt" in plan.resolved
    assert "offline-tts" in plan.resolved
    assert "offline-llm" in plan.resolved
    assert plan.installed_size_mb > 10000


def test_unknown_custom_component_is_rejected() -> None:
    try:
        component_registry.plan(InstallPreset.CUSTOM, requested=["unknown-component"])
    except KeyError as exc:
        assert exc.args[0] == "unknown-component"
    else:
        raise AssertionError("unknown component should fail")


def test_component_api_exposes_recommended_install_plan() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/components/plan/install?preset=recommended")
    assert response.status_code == 200
    payload = response.json()
    assert payload["preset"] == "recommended"
    assert "aircraft-fa18c" in payload["resolved"]
