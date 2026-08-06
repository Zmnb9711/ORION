from pathlib import Path

from orion.mission_catalog import (
    MissionSearchRoot,
    MissionSource,
    default_search_roots,
    discover_missions,
)


def test_default_search_roots_include_dcs_variants(tmp_path: Path) -> None:
    roots = default_search_roots(saved_games=tmp_path)

    assert MissionSearchRoot(tmp_path / "DCS" / "Missions", MissionSource.USER) in roots
    assert MissionSearchRoot(tmp_path / "DCS.openbeta" / "Missions", MissionSource.USER) in roots


def test_discover_missions_classifies_and_deduplicates(tmp_path: Path) -> None:
    user_root = tmp_path / "Saved Games" / "DCS" / "Missions"
    custom_root = tmp_path / "Custom"
    user_root.mkdir(parents=True)
    custom_root.mkdir()

    user_mission = user_root / "Operation Desert.miz"
    prepared_mission = user_root / "Operation Desert (ORION).miz"
    custom_mission = custom_root / "Training CAS.miz"

    user_mission.write_bytes(b"mission")
    prepared_mission.write_bytes(b"prepared")
    custom_mission.write_bytes(b"custom")

    records = discover_missions(
        [MissionSearchRoot(user_root, MissionSource.USER)],
        custom_directories=[custom_root],
    )

    assert {record.name for record in records} == {
        "Operation Desert",
        "Operation Desert (ORION)",
        "Training CAS",
    }

    prepared = next(record for record in records if record.name.endswith("(ORION)"))
    assert prepared.prepared_for_orion is True
    assert prepared.source is MissionSource.USER

    custom = next(record for record in records if record.name == "Training CAS")
    assert custom.source is MissionSource.CUSTOM
