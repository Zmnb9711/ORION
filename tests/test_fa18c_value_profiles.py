from pathlib import Path
from unittest.mock import patch

import pytest

from orion.fa18c_value_profiles import ControlValueProfile, HornetValueProfileRegistry, HornetValueProfileSet, calibrated_detents


def test_calibrated_detents_deduplicates_repeated_transitions() -> None:
    values = calibrated_detents([(0.0, 0.1), (0.1, 0.2), (0.2, 0.1005), (0.1005, 0.0)])
    assert values == [0.0, 0.1, 0.2]


def test_profile_matches_only_near_calibrated_detent() -> None:
    profile = ControlValueProfile(control="selector", argument_id=10, detents=[0.0, 0.25, 0.5], tolerance=0.02)
    assert profile.nearest_index(0.251) == 1
    assert profile.nearest_index(0.31) is None


def test_registry_round_trip(tmp_path: Path) -> None:
    registry = HornetValueProfileRegistry(tmp_path / "profiles.json")
    saved = registry.save(HornetValueProfileSet(mapping_version="map-v1", controls={
        "tacan_xy": ControlValueProfile(control="tacan_xy", argument_id=413, detents=[0.0, 1.0])
    }))
    assert saved.mapping_version == "map-v1"
    loaded = HornetValueProfileRegistry(tmp_path / "profiles.json").load()
    assert loaded is not None
    assert loaded.controls["tacan_xy"].detents == [0.0, 1.0]


def test_registry_invalid_profile_is_treated_as_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("{not valid json", encoding="utf-8")
    registry = HornetValueProfileRegistry(path)

    assert registry.load() is None
    assert registry.current() is None


def test_registry_does_not_hide_unexpected_programming_errors(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text('{"mapping_version":"map-v1"}', encoding="utf-8")
    registry = HornetValueProfileRegistry(path)

    with patch.object(HornetValueProfileSet, "model_validate_json", side_effect=RuntimeError("unexpected defect")):
        with pytest.raises(RuntimeError, match="unexpected defect"):
            registry.load()
