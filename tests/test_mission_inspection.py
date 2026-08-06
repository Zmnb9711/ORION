import json
from zipfile import ZipFile

from orion.mission_preparation import (
    MANIFEST_ARCHIVE_PATH,
    PACK_ARCHIVE_PATH,
    MissionActivationStatus,
    inspect_mission,
)


def _make_miz(path, mission_text: str = "mission = {}", include_pack: bool = False) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("mission", mission_text)
        archive.writestr("options", "options = {}")
        if include_pack:
            archive.writestr(PACK_ARCHIVE_PATH, "ORION = {}")
            archive.writestr(
                MANIFEST_ARCHIVE_PATH,
                json.dumps({"schema": "orion.mission-pack-manifest.v1"}),
            )


def test_inspection_reports_unprepared_mission(tmp_path) -> None:
    mission = tmp_path / "Plain.miz"
    _make_miz(mission)

    result = inspect_mission(str(mission))

    assert result.valid_archive is True
    assert result.activation_status is MissionActivationStatus.NOT_PREPARED
    assert result.mission_pack_present is False


def test_inspection_reports_embedded_pack_without_trigger(tmp_path) -> None:
    mission = tmp_path / "Embedded.miz"
    _make_miz(mission, include_pack=True)

    result = inspect_mission(str(mission))

    assert result.activation_status is MissionActivationStatus.EMBEDDED_ONLY
    assert result.activation_reference is None
    assert result.warnings


def test_inspection_detects_activation_reference(tmp_path) -> None:
    mission = tmp_path / "Activated.miz"
    _make_miz(
        mission,
        mission_text='mission = {} -- ORION_MissionPack.lua',
        include_pack=True,
    )

    result = inspect_mission(str(mission))

    assert result.activation_status is MissionActivationStatus.TRIGGER_DETECTED
    assert result.activation_reference == "ORION_MissionPack.lua"
    assert result.warnings == []
