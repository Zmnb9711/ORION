from pathlib import Path

from orion.setup_wizard_model import SetupStep, SetupWizardState


def _make_dcs(root: Path) -> Path:
    (root / "bin-mt").mkdir(parents=True)
    (root / "bin-mt" / "DCS.exe").write_bytes(b"")
    return root


def _ready_state(tmp_path: Path) -> SetupWizardState:
    dcs = _make_dcs(tmp_path / "DCS World")
    saved = tmp_path / "Saved Games" / "DCS"
    saved.mkdir(parents=True)
    state = SetupWizardState()
    assert state.select_dcs(str(dcs))
    assert state.select_saved_games(str(saved))
    state.mark_integration(True)
    state.mark_telemetry(True)
    assert state.ready
    return state


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


def test_changing_dcs_invalidates_saved_games_and_ready_state(tmp_path: Path):
    state = _ready_state(tmp_path)
    replacement = _make_dcs(tmp_path / "DCS World 2")

    assert state.select_dcs(str(replacement))

    assert state.step == SetupStep.SAVED_GAMES
    assert state.saved_games_path is None
    assert not state.integration_ready
    assert not state.telemetry_ready
    assert not state.can_install
    assert not state.can_test
    assert not state.ready


def test_changing_saved_games_invalidates_integration_and_telemetry(tmp_path: Path):
    state = _ready_state(tmp_path)
    replacement = tmp_path / "Saved Games" / "DCS.openbeta"
    replacement.mkdir(parents=True)

    assert state.select_saved_games(str(replacement))

    assert state.step == SetupStep.INTEGRATION
    assert state.saved_games_path == str(replacement)
    assert state.can_install
    assert not state.integration_ready
    assert not state.telemetry_ready
    assert not state.can_test
    assert not state.ready


def test_failed_integration_clears_previous_telemetry_success(tmp_path: Path):
    state = _ready_state(tmp_path)

    state.mark_integration(False)

    assert state.step == SetupStep.INTEGRATION
    assert not state.integration_ready
    assert not state.telemetry_ready
    assert not state.ready


def test_telemetry_cannot_mark_setup_ready_before_integration(tmp_path: Path):
    dcs = _make_dcs(tmp_path / "DCS World")
    saved = tmp_path / "Saved Games" / "DCS"
    saved.mkdir(parents=True)
    state = SetupWizardState()
    assert state.select_dcs(str(dcs))
    assert state.select_saved_games(str(saved))

    state.mark_telemetry(True)

    assert state.step == SetupStep.TELEMETRY
    assert not state.telemetry_ready
    assert not state.ready
