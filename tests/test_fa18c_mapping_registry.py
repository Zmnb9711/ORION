from pathlib import Path
from unittest.mock import patch

import pytest

from orion.fa18c_calibration_wizard import CalibrationStatus, hornet_calibration_wizard
from orion.fa18c_diagnostics_recorder import hornet_diagnostics_recorder
from orion.fa18c_mapping_registry import HornetMappingRegistry, hornet_mapping_registry


ARGUMENTS = {
    "tacan_power": 410,
    "tacan_channel_tens": 411,
    "tacan_channel_ones": 412,
    "tacan_xy": 413,
    "comm1_selector": 133,
    "comm2_selector": 134,
}


def packet(argument_id: int, value: float, previous: float) -> dict:
    return {
        "mode": "cockpit_argument_changes",
        "aircraft_id": "fa-18c",
        "range": {"start": 0, "stop": 600},
        "changes": [{"id": argument_id, "value": value, "previous": previous}],
    }


def test_registry_persists_and_loads_validated_mapping(tmp_path: Path) -> None:
    path = tmp_path / "mapping.json"
    registry = HornetMappingRegistry(path)
    saved = registry.save(ARGUMENTS, {"tacan_power": 0.95})
    assert saved.complete()
    assert saved.validated is True
    assert path.exists()

    loaded = HornetMappingRegistry(path)
    assert loaded.load() is not None
    assert loaded.current() is not None
    assert loaded.current().arguments["comm1_selector"] == 133


def test_registry_returns_none_for_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "mapping.json"
    path.write_text("{not-json", encoding="utf-8")
    registry = HornetMappingRegistry(path)
    assert registry.load() is None
    assert registry.current() is None


def test_registry_does_not_hide_unexpected_programming_errors(tmp_path: Path) -> None:
    path = tmp_path / "mapping.json"
    path.write_text("{}", encoding="utf-8")
    registry = HornetMappingRegistry(path)
    with patch("orion.fa18c_mapping_registry.HornetArgumentMapping.model_validate", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            registry.load()


def test_registry_rejects_incomplete_mapping(tmp_path: Path) -> None:
    registry = HornetMappingRegistry(tmp_path / "mapping.json")
    with pytest.raises(ValueError, match="Incomplete Hornet mapping"):
        registry.save({"tacan_power": 410})


def test_mapping_builds_dcs_runtime_command(tmp_path: Path) -> None:
    registry = HornetMappingRegistry(tmp_path / "mapping.json")
    mapping = registry.save(ARGUMENTS)
    command = mapping.dcs_command()
    assert command["command"] == "set_cockpit_mapping"
    assert command["mapping_version"] == "fa18c-clickable-calibrated-v1"
    assert command["tacan_power_id"] == 410
    assert command["comm2_selector_id"] == 134


def test_completed_wizard_persists_mapping(tmp_path: Path) -> None:
    original_path = hornet_mapping_registry.path
    hornet_mapping_registry.clear()
    hornet_mapping_registry.path = tmp_path / "wizard-mapping.json"
    hornet_calibration_wizard.cancel()
    hornet_diagnostics_recorder.clear()
    try:
        session = hornet_calibration_wizard.start()
        ids = [410, 411, 412, 413, 133, 134]
        for argument_id in ids:
            for previous, value in [(0.0, 1.0), (1.0, 0.0), (0.0, 1.0)]:
                hornet_diagnostics_recorder.ingest(packet(argument_id, value, previous))
            session = hornet_calibration_wizard.evaluate_step()
        assert session.status == CalibrationStatus.COMPLETE
        assert session.mapping_version == "fa18c-clickable-calibrated-v1"
        mapping = hornet_mapping_registry.current()
        assert mapping is not None
        assert mapping.arguments == ARGUMENTS
    finally:
        hornet_calibration_wizard.cancel()
        hornet_diagnostics_recorder.clear()
        hornet_mapping_registry.clear()
        hornet_mapping_registry.path = original_path


def test_export_supports_runtime_validated_mapping() -> None:
    export = Path("dcs-export/Export.lua").read_text(encoding="utf-8")
    assert 'command == "set_cockpit_mapping"' in export
    assert "cockpitMapping.validated = false" not in export
    assert "nextMapping.validated = true" in export
    assert "safeArgument(main, cockpitMapping.tacan_power)" in export
