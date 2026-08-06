from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from pydantic import BaseModel


PACK_ARCHIVE_PATH = "l10n/DEFAULT/ORION_MissionPack.lua"
MANIFEST_ARCHIVE_PATH = "orion/manifest.json"


class MissionPreparationRequest(BaseModel):
    source_mission: str
    mission_pack_script: str
    output_directory: str | None = None
    overwrite_existing_copy: bool = False


class MissionPreparationResult(BaseModel):
    source_mission: str
    prepared_mission: str
    backup_mission: str
    source_sha256: str
    prepared_sha256: str
    mission_pack_archive_path: str = PACK_ARCHIVE_PATH
    activation_required: bool = True
    message: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_miz(path: Path) -> None:
    if path.suffix.lower() != ".miz":
        raise ValueError("source_mission must be a .miz file")
    if not path.is_file():
        raise FileNotFoundError(f"Mission not found: {path}")
    try:
        with ZipFile(path, "r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f"Corrupt .miz archive member: {bad_member}")
    except BadZipFile as exc:
        raise ValueError("source_mission is not a valid .miz archive") from exc


def _prepared_name(source: Path) -> str:
    stem = source.stem
    if stem.endswith(" (ORION)"):
        return source.name
    return f"{stem} (ORION){source.suffix}"


def prepare_mission(request: MissionPreparationRequest) -> MissionPreparationResult:
    source = Path(request.source_mission).expanduser().resolve()
    pack = Path(request.mission_pack_script).expanduser().resolve()
    _validate_miz(source)

    if not pack.is_file() or pack.suffix.lower() != ".lua":
        raise FileNotFoundError(f"Mission Pack Lua script not found: {pack}")

    output_directory = (
        Path(request.output_directory).expanduser().resolve()
        if request.output_directory
        else source.parent
    )
    output_directory.mkdir(parents=True, exist_ok=True)

    prepared = output_directory / _prepared_name(source)
    backup = output_directory / f"{source.name}.orion-backup"

    if prepared.exists() and not request.overwrite_existing_copy:
        raise FileExistsError(f"Prepared mission already exists: {prepared}")

    # A byte-identical backup is created even though the original mission is never edited.
    shutil.copy2(source, backup)

    source_hash = _sha256(source)
    manifest = {
        "schema": "orion.mission-pack-manifest.v1",
        "prepared_at": datetime.now(UTC).isoformat(),
        "source_name": source.name,
        "source_sha256": source_hash,
        "mission_pack_file": PACK_ARCHIVE_PATH,
        "activation": "pending-trigger-injection",
    }

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="orion-mission-", suffix=".miz", dir=output_directory, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)

        shutil.copy2(source, temporary_path)
        with ZipFile(temporary_path, "a", compression=ZIP_DEFLATED) as archive:
            archive.writestr(PACK_ARCHIVE_PATH, pack.read_bytes())
            archive.writestr(
                MANIFEST_ARCHIVE_PATH,
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )

        _validate_miz(temporary_path)
        if prepared.exists():
            prepared.unlink()
        temporary_path.replace(prepared)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return MissionPreparationResult(
        source_mission=str(source),
        prepared_mission=str(prepared),
        backup_mission=str(backup),
        source_sha256=source_hash,
        prepared_sha256=_sha256(prepared),
        activation_required=True,
        message=(
            "Mission Pack embedded in a separate ORION copy. "
            "Automatic Mission Editor trigger injection is not implemented yet."
        ),
    )
