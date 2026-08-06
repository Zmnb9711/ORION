from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from pydantic import BaseModel


PACK_ARCHIVE_PATH = "l10n/DEFAULT/ORION_MissionPack.lua"
MANIFEST_ARCHIVE_PATH = "orion/manifest.json"
MISSION_ARCHIVE_PATH = "mission"


class MissionActivationStatus(StrEnum):
    NOT_PREPARED = "not_prepared"
    EMBEDDED_ONLY = "embedded_only"
    TRIGGER_DETECTED = "trigger_detected"


class MissionPreparationRequest(BaseModel):
    source_mission: str
    mission_pack_script: str
    output_directory: str | None = None
    overwrite_existing_copy: bool = False


class MissionInspectionResult(BaseModel):
    mission_path: str
    valid_archive: bool
    mission_entry_present: bool
    mission_pack_present: bool
    manifest_present: bool
    activation_status: MissionActivationStatus
    activation_reference: str | None = None
    warnings: list[str]


class MissionPreparationResult(BaseModel):
    source_mission: str
    prepared_mission: str
    backup_mission: str
    source_sha256: str
    prepared_sha256: str
    mission_pack_archive_path: str = PACK_ARCHIVE_PATH
    activation_required: bool = True
    inspection: MissionInspectionResult
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


def _decode_mission_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def inspect_mission(mission_path: str) -> MissionInspectionResult:
    path = Path(mission_path).expanduser().resolve()
    _validate_miz(path)

    warnings: list[str] = []
    mission_entry_present = False
    mission_pack_present = False
    manifest_present = False
    activation_reference: str | None = None

    with ZipFile(path, "r") as archive:
        members = set(archive.namelist())
        mission_entry_present = MISSION_ARCHIVE_PATH in members
        mission_pack_present = PACK_ARCHIVE_PATH in members
        manifest_present = MANIFEST_ARCHIVE_PATH in members

        if mission_entry_present:
            mission_text = _decode_mission_text(archive.read(MISSION_ARCHIVE_PATH))
            references = (
                PACK_ARCHIVE_PATH,
                "ORION_MissionPack.lua",
                "ORION_MISSION_PACK",
            )
            activation_reference = next(
                (reference for reference in references if reference in mission_text),
                None,
            )
        else:
            warnings.append("The .miz archive has no mission entry")

    if not mission_pack_present:
        status = MissionActivationStatus.NOT_PREPARED
        warnings.append("ORION Mission Pack is not embedded")
    elif activation_reference:
        status = MissionActivationStatus.TRIGGER_DETECTED
    else:
        status = MissionActivationStatus.EMBEDDED_ONLY
        warnings.append(
            "Mission Pack is embedded but no activation reference was detected in the mission data"
        )

    if mission_pack_present and not manifest_present:
        warnings.append("ORION manifest is missing")

    return MissionInspectionResult(
        mission_path=str(path),
        valid_archive=True,
        mission_entry_present=mission_entry_present,
        mission_pack_present=mission_pack_present,
        manifest_present=manifest_present,
        activation_status=status,
        activation_reference=activation_reference,
        warnings=warnings,
    )


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

    # The original mission is never edited. The backup is byte-identical to it.
    shutil.copy2(source, backup)

    source_hash = _sha256(source)
    manifest = {
        "schema": "orion.mission-pack-manifest.v1",
        "prepared_at": datetime.now(UTC).isoformat(),
        "source_name": source.name,
        "source_sha256": source_hash,
        "mission_pack_file": PACK_ARCHIVE_PATH,
        "activation": "embedded-only",
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

    inspection = inspect_mission(str(prepared))
    activation_required = (
        inspection.activation_status is not MissionActivationStatus.TRIGGER_DETECTED
    )

    return MissionPreparationResult(
        source_mission=str(source),
        prepared_mission=str(prepared),
        backup_mission=str(backup),
        source_sha256=source_hash,
        prepared_sha256=_sha256(prepared),
        activation_required=activation_required,
        inspection=inspection,
        message=(
            "Mission Pack embedded and archive validated. "
            "A DCS trigger is still required before mission-level commands can run."
            if activation_required
            else "Mission Pack embedded and an activation reference was detected."
        ),
    )
