import json
from zipfile import ZipFile

import pytest

from orion.mission_preparation import (
    MANIFEST_ARCHIVE_PATH,
    PACK_ARCHIVE_PATH,
    MissionPreparationRequest,
    prepare_mission,
)


def _make_miz(path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("mission", "mission = {}")
        archive.writestr("options", "options = {}")


def test_prepare_mission_creates_copy_backup_and_manifest(tmp_path) -> None:
    source = tmp_path / "Training.miz"
    pack = tmp_path / "ORION_MissionPack.lua"
    _make_miz(source)
    pack.write_text("ORION = {}", encoding="utf-8")

    result = prepare_mission(
        MissionPreparationRequest(
            source_mission=str(source),
            mission_pack_script=str(pack),
        )
    )

    prepared = tmp_path / "Training (ORION).miz"
    backup = tmp_path / "Training.miz.orion-backup"
    assert prepared.exists()
    assert backup.read_bytes() == source.read_bytes()
    assert source.exists()
    assert result.activation_required is True

    with ZipFile(prepared, "r") as archive:
        assert archive.read(PACK_ARCHIVE_PATH) == b"ORION = {}"
        manifest = json.loads(archive.read(MANIFEST_ARCHIVE_PATH))
        assert manifest["source_name"] == "Training.miz"
        assert manifest["activation"] == "pending-trigger-injection"


def test_prepare_mission_does_not_overwrite_existing_copy_by_default(tmp_path) -> None:
    source = tmp_path / "Training.miz"
    pack = tmp_path / "ORION_MissionPack.lua"
    _make_miz(source)
    pack.write_text("ORION = {}", encoding="utf-8")
    (tmp_path / "Training (ORION).miz").write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        prepare_mission(
            MissionPreparationRequest(
                source_mission=str(source),
                mission_pack_script=str(pack),
            )
        )


def test_prepare_mission_rejects_invalid_archive(tmp_path) -> None:
    source = tmp_path / "Broken.miz"
    pack = tmp_path / "ORION_MissionPack.lua"
    source.write_text("not a zip", encoding="utf-8")
    pack.write_text("ORION = {}", encoding="utf-8")

    with pytest.raises(ValueError, match="valid .miz"):
        prepare_mission(
            MissionPreparationRequest(
                source_mission=str(source),
                mission_pack_script=str(pack),
            )
        )
