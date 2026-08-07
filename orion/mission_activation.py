from __future__ import annotations

import tempfile
from enum import StrEnum
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from pydantic import BaseModel

from orion.mission_preparation import PACK_ARCHIVE_PATH


SAFE_TRIGGER_SLOT = "-- ORION_SAFE_TRIGGER_SLOT"
ACTIVATION_SNIPPET = (
    "\n-- ORION Mission Pack activation\n"
    "do\n"
    "  local ok, err = pcall(dofile, 'l10n/DEFAULT/ORION_MissionPack.lua')\n"
    "  if not ok then trigger.action.outText('ORION Mission Pack failed: ' .. tostring(err), 15) end\n"
    "end\n"
)


class ActivationMode(StrEnum):
    MANUAL = "manual"
    GUARDED = "guarded"
    ALREADY_ACTIVE = "already_active"


class MissionActivationPlan(BaseModel):
    mission_path: str
    mode: ActivationMode
    can_apply_automatically: bool
    reason: str
    steps: list[str]


def plan_activation(mission_path: str) -> MissionActivationPlan:
    path = Path(mission_path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".miz":
        raise FileNotFoundError(f"Mission not found: {path}")

    try:
        with ZipFile(path, "r") as archive:
            names = set(archive.namelist())
            if PACK_ARCHIVE_PATH not in names:
                return MissionActivationPlan(
                    mission_path=str(path),
                    mode=ActivationMode.MANUAL,
                    can_apply_automatically=False,
                    reason="Mission Pack is not embedded in this mission",
                    steps=["Prepare an ORION copy of the mission first"],
                )
            if "mission" not in names:
                return MissionActivationPlan(
                    mission_path=str(path),
                    mode=ActivationMode.MANUAL,
                    can_apply_automatically=False,
                    reason="The .miz archive has no mission definition",
                    steps=["Open the mission in DCS Mission Editor and re-save it"],
                )
            mission_text = archive.read("mission").decode("utf-8", errors="replace")
    except BadZipFile as exc:
        raise ValueError("mission_path is not a valid .miz archive") from exc

    if PACK_ARCHIVE_PATH in mission_text or "ORION Mission Pack activation" in mission_text:
        return MissionActivationPlan(
            mission_path=str(path),
            mode=ActivationMode.ALREADY_ACTIVE,
            can_apply_automatically=False,
            reason="Mission Pack activation is already referenced",
            steps=[],
        )

    if SAFE_TRIGGER_SLOT in mission_text:
        return MissionActivationPlan(
            mission_path=str(path),
            mode=ActivationMode.GUARDED,
            can_apply_automatically=True,
            reason="A dedicated ORION safe activation slot is present",
            steps=["Replace the ORION safe activation slot", "Validate the resulting .miz archive"],
        )

    return MissionActivationPlan(
        mission_path=str(path),
        mode=ActivationMode.MANUAL,
        can_apply_automatically=False,
        reason="Unknown mission trigger structure; automatic editing is refused",
        steps=[
            "Open the prepared copy in DCS Mission Editor",
            "Add a MISSION START trigger",
            "Add a DO SCRIPT FILE action for ORION_MissionPack.lua",
            "Save the mission as the ORION copy",
            "Run ORION inspection again",
        ],
    )


def apply_guarded_activation(mission_path: str) -> MissionActivationPlan:
    plan = plan_activation(mission_path)
    if plan.mode is ActivationMode.ALREADY_ACTIVE:
        return plan
    if not plan.can_apply_automatically:
        raise ValueError(plan.reason)

    path = Path(plan.mission_path)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="orion-activate-", suffix=".miz", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)

        with ZipFile(path, "r") as source, ZipFile(
            temporary_path, "w", compression=ZIP_DEFLATED
        ) as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "mission":
                    text = data.decode("utf-8", errors="strict")
                    if text.count(SAFE_TRIGGER_SLOT) != 1:
                        raise ValueError("Expected exactly one ORION safe activation slot")
                    data = text.replace(SAFE_TRIGGER_SLOT, ACTIVATION_SNIPPET, 1).encode("utf-8")
                target.writestr(item, data)

        with ZipFile(temporary_path, "r") as archive:
            if archive.testzip() is not None:
                raise ValueError("Activated mission archive failed validation")
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return plan_activation(str(path))
