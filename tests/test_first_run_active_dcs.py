from pathlib import Path

from orion.active_dcs_installation import ActiveDcsInstallation, ActiveDcsInstallationStore
from orion.dcs_installations import DcsInstallationStore, DcsInstallationType
from orion.first_run_wizard import FirstRunRequest, FirstRunState, evaluate_first_run


def test_first_run_requires_explicit_active_selection(tmp_path: Path):
    store = DcsInstallationStore()
    active = ActiveDcsInstallationStore(tmp_path / "active.json")
    report = evaluate_first_run(FirstRunRequest(), installation_store=store, active_store=active)
    check = next(item for item in report.checks if item.key == "dcs_installation")
    assert not check.passed
    assert check.blocking
    assert report.state == FirstRunState.ACTION_REQUIRED


def test_first_run_uses_active_steam_selection_and_saved_games(tmp_path: Path, monkeypatch):
    dcs = tmp_path / "DCSWorld" / "bin" / "DCS.exe"
    dcs.parent.mkdir(parents=True)
    dcs.write_bytes(b"")
    saved = tmp_path / "Saved Games" / "DCS"
    scripts = saved / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "Export.lua").write_text('dofile(lfs.writedir() .. "Scripts/ORION/Export.lua")\n', encoding="utf-8")

    active = ActiveDcsInstallationStore(tmp_path / "active.json")
    active.set(ActiveDcsInstallation(
        installation_type=DcsInstallationType.STEAM,
        executable_path=str(dcs),
        install_root=str(dcs.parents[1]),
        saved_games_path=str(saved),
        display_name="DCS Steam",
    ))

    monkeypatch.setattr("orion.first_run_wizard.component_registry.get", lambda component_id: object())
    report = evaluate_first_run(
        FirstRunRequest(
            installed_components=["orion-core", "dcs-integration", "aircraft-fa18c"],
            telemetry_received=True,
            aircraft_type="FA-18C_hornet",
        ),
        active_store=active,
    )
    assert report.installation_type == DcsInstallationType.STEAM
    assert report.active_dcs_display_name == "DCS Steam"
    assert report.selected_saved_games == str(saved)
    assert report.state == FirstRunState.READY_TO_FLY
