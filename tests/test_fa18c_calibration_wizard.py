from orion.fa18c_calibration_wizard import CalibrationStatus, hornet_calibration_wizard
from orion.fa18c_diagnostics_recorder import hornet_diagnostics_recorder


def packet(argument_id: int, value: float, previous: float) -> dict:
    return {
        "mode": "cockpit_argument_changes",
        "aircraft_id": "fa-18c",
        "range": {"start": 0, "stop": 600},
        "changes": [{"id": argument_id, "value": value, "previous": previous}],
    }


def setup_function() -> None:
    hornet_calibration_wizard.cancel()
    hornet_diagnostics_recorder.clear()


def test_wizard_starts_with_tacan_power_instruction() -> None:
    session = hornet_calibration_wizard.start()
    assert session.status == CalibrationStatus.RUNNING
    assert session.active_step is not None
    assert session.active_step.key == "tacan_power"
    assert "TACAN" in session.active_step.instruction_ru


def test_wizard_accepts_repeated_marker_candidate_and_advances() -> None:
    session = hornet_calibration_wizard.start()
    for previous, value in [(0.0, 1.0), (1.0, 0.0), (0.0, 1.0)]:
        hornet_diagnostics_recorder.ingest(packet(410, value, previous))
    updated = hornet_calibration_wizard.evaluate_step()
    result = next(item for item in updated.results if item.key == "tacan_power")
    assert result.accepted_argument_id == 410
    assert result.confidence >= 0.65
    assert updated.current_step == 1
    assert updated.active_step is not None
    assert updated.active_step.key == "tacan_channel_tens"


def test_wizard_requests_retry_when_evidence_is_missing() -> None:
    hornet_calibration_wizard.start()
    session = hornet_calibration_wizard.evaluate_step()
    assert session.status == CalibrationStatus.NEEDS_RETRY
    assert session.results[-1].accepted_argument_id is None
    retried = hornet_calibration_wizard.retry()
    assert retried.status == CalibrationStatus.RUNNING
