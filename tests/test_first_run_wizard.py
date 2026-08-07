from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.dcs_installations import DcsInstallationCreate, dcs_installations
from orion.dcs_readiness import install_export_integration
from orion.first_run_wizard import FirstRunRequest, FirstRunState, evaluate_first_run


RECOMMENDED = ["orion-core", "dcs-integration", "aircraft-fa18c", "online-voice"]


def _register_dcs(tmp_path: Path):
    executable = tmp_path / "DCS.exe"
    executable.write_text("stub", encoding="utf-8")
    return dcs_installations.create(DcsInstallationCreate(name="Test DCS", executable_path=str(executable)))


def test_first_run_waits_for_live_dcs_after_setup(tmp_path: Path) -> None:
    item = _register_dcs(tmp_path)
    saved_games = tmp_path / "Saved Games" / "DCS"
    install_export_integration(str(saved_games))
    try:
        report = evaluate_first_run(FirstRunRequest(saved_games_path=str(saved_games), installed_components=RECOMMENDED))
        assert report.state == FirstRunState.WAITING_FOR_DCS
        assert report.headline == "Setup complete — waiting for DCS"
        assert report.next_action == "Start DCS and enter the F/A-18C"
    finally:
        dcs_installations.delete(item.installation_id)


def test_first_run_reaches_ready_to_fly_after_telemetry(tmp_path: Path) -> None:
    item = _register_dcs(tmp_path)
    saved_games = tmp_path / "Saved Games" / "DCS"
    install_export_integration(str(saved_games))
    try:
        report = evaluate_first_run(
            FirstRunRequest(
                saved_games_path=str(saved_games),
                installed_components=RECOMMENDED,
                telemetry_received=True,
                aircraft_type="FA-18C_hornet",
            )
        )
        assert report.state == FirstRunState.READY_TO_FLY
        assert report.headline == "READY TO FLY"
        telemetry = next(check for check in report.checks if check.key == "telemetry")
        assert telemetry.passed is True
        assert "FA-18C_hornet" in telemetry.message
    finally:
        dcs_installations.delete(item.installation_id)


def test_first_run_reports_first_blocking_action_without_dcs() -> None:
    report = evaluate_first_run(FirstRunRequest(installed_components=RECOMMENDED))
    assert report.state == FirstRunState.ACTION_REQUIRED
    assert report.next_action == "Detect or select DCS.exe"


def test_first_run_api(tmp_path: Path) -> None:
    item = _register_dcs(tmp_path)
    saved_games = tmp_path / "Saved Games" / "DCS"
    install_export_integration(str(saved_games))
    try:
        response = TestClient(app).post(
            "/v1/first-run/status",
            json={
                "saved_games_path": str(saved_games),
                "installed_components": RECOMMENDED,
                "telemetry_received": True,
                "aircraft_type": "FA-18C_hornet",
            },
        )
        assert response.status_code == 200
        assert response.json()["state"] == "ready_to_fly"
    finally:
        dcs_installations.delete(item.installation_id)
