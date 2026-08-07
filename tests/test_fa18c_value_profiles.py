from pathlib import Path

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
