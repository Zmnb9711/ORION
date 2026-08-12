from pathlib import Path

from orion.setup_wizard_model import SetupStep, SetupWizardState


def _make_dcs(root: Path) -> Path:
    (root / "bin-mt").mkdir(parents=True)
    (root / "bin-mt" / "DCS.exe").write_bytes(b"")
    return root


def test_invalid_dcs_folder_does_not_advance(tmp_path: Path):
    state = SetupWizardState()
    assert not state.select_dcs(str(tmp_path / "missing"))
    assert state.step == SetupStep.DCS
    assert state.candidate is None
    assert state.error


def test_manual_dcs_and_saved_games_advance_deterministically(tmp_path: Path):
    dcs = _make_dcs(tmp_path / "DCS World")
    saved = tmp_path / "Saved Games" / "DCS"
    saved.mkdir(parents=True)
    state = SetupWizardState()

    assert state.select_dcs(str(dcs))
    assert state.step == SetupStep.SAVED_GAMES
    assert state.select_saved_games(str(saved))
    assert state.step == SetupStep.INTEGRATION
    assert state.can_install
    assert not state.can_test

    state.mark_integration(True)
    assert state.step == SetupStep.TELEMETRY
    assert state.can_test
    state.mark_telemetry(True)
    assert state.step == SetupStep.READY
    assert state.ready


def test_failed_telemetry_stays_on_telemetry_step(tmp_path: Path):
    dcs = _make_dcs(tmp_path / "DCS World")
    saved = tmp_path / "Saved Games" / "DCS.custom"
    saved.mkdir(parents=True)
    state = SetupWizardState()
    assert state.select_dcs(str(dcs))
    assert state.select_saved_games(str(saved))
    state.mark_integration(True)
    state.mark_telemetry(False)
    assert state.step == SetupStep.TELEMETRY
    assert not state.ready
    assert state.error == "Waiting for live telemetry from DCS"
