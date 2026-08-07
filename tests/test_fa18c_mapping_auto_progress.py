from orion.fa18c_calibration_wizard import CalibrationStatus, hornet_calibration_wizard
from orion.fa18c_diagnostics_recorder import hornet_diagnostics_recorder
from orion.fa18c_mapping_auto_progress import hornet_mapping_auto_progress


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
    hornet_mapping_auto_progress.clear()


def test_auto_progress_waits_until_evidence_is_sufficient() -> None:
    hornet_calibration_wizard.start()
    hornet_diagnostics_recorder.ingest(packet(410, 1.0, 0.0))
    assert hornet_mapping_auto_progress.on_diagnostics_packet() is None
    assert hornet_calibration_wizard.current().current_step == 0


def test_auto_progress_advances_after_confident_repeated_changes() -> None:
    hornet_calibration_wizard.start()
    event = None
    for previous, value in [(0.0, 1.0), (1.0, 0.0), (0.0, 1.0)]:
        hornet_diagnostics_recorder.ingest(packet(410, value, previous))
        event = hornet_mapping_auto_progress.on_diagnostics_packet() or event

    assert event is not None
    assert event.advanced is True
    assert event.previous_step == "tacan_power"
    assert event.next_step == "tacan_channel_tens"
    assert hornet_calibration_wizard.current().current_step == 1


def test_auto_progress_does_not_advance_ambiguous_candidates() -> None:
    hornet_calibration_wizard.start()
    for argument_id in (410, 999):
        for previous, value in [(0.0, 1.0), (1.0, 0.0), (0.0, 1.0)]:
            hornet_diagnostics_recorder.ingest(packet(argument_id, value, previous))
    event = hornet_mapping_auto_progress.on_diagnostics_packet()
    assert event is None
    assert hornet_calibration_wizard.current().status == CalibrationStatus.RUNNING
    assert hornet_calibration_wizard.current().current_step == 0
