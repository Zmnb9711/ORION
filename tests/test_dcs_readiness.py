from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.dcs_readiness import ORION_EXPORT_LINE, ReadinessState, install_export_integration, remove_export_integration


def test_export_install_preserves_existing_export_and_is_idempotent(tmp_path: Path) -> None:
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    export = scripts / "Export.lua"
    export.write_text("-- existing integration\n", encoding="utf-8")

    first = install_export_integration(str(tmp_path))
    second = install_export_integration(str(tmp_path))
    content = export.read_text(encoding="utf-8")
    integration = scripts / "ORION" / "Export.lua"
    integration_content = integration.read_text(encoding="utf-8")

    assert first.state == ReadinessState.READY
    assert second.export_configured is True
    assert "-- existing integration" in content
    assert content.count(ORION_EXPORT_LINE) == 1
    assert integration.is_file()
    assert "-- ORION DCS Export telemetry bridge" in integration_content
    assert '"protocol_version":"0.3"' in integration_content
    assert "ORION_TELEMETRY_PORT = 45100" in integration_content
    assert "Runtime telemetry exporter will be installed/updated" not in integration_content


def test_export_remove_preserves_shared_export_content(tmp_path: Path) -> None:
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    export = scripts / "Export.lua"
    export.write_text("-- existing integration\nother_exporter = true\n", encoding="utf-8")

    install_export_integration(str(tmp_path))
    integration = scripts / "ORION" / "Export.lua"
    assert integration.is_file()
    assert ORION_EXPORT_LINE in export.read_text(encoding="utf-8")

    report = remove_export_integration(str(tmp_path))
    content = export.read_text(encoding="utf-8")
    assert report.export_configured is False
    assert "-- existing integration" in content
    assert "other_exporter = true" in content
    assert ORION_EXPORT_LINE not in content
    assert not integration.exists()


def test_export_remove_deletes_empty_orion_only_export_file(tmp_path: Path) -> None:
    install_export_integration(str(tmp_path))
    export = tmp_path / "Scripts" / "Export.lua"
    assert export.is_file()

    remove_export_integration(str(tmp_path))
    assert not export.exists()


def test_readiness_api_can_install_export(tmp_path: Path) -> None:
    client = TestClient(app)
    before = client.get("/v1/dcs-readiness", params={"saved_games_path": str(tmp_path)})
    assert before.status_code == 200
    assert before.json()["state"] == "action_required"

    installed = client.post("/v1/dcs-readiness/export", json={"saved_games_path": str(tmp_path)})
    assert installed.status_code == 200
    assert installed.json()["state"] == "ready"
    assert installed.json()["export_configured"] is True
