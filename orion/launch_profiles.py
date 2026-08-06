from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class DcsLaunchMode(StrEnum):
    DESKTOP = "desktop"
    OPENXR = "openxr"
    STEAMVR = "steamvr"


class DcsLaunchProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    mode: DcsLaunchMode = DcsLaunchMode.OPENXR
    dcs_executable: str
    mission_path: str | None = None
    extra_arguments: list[str] = Field(default_factory=list)
    orion_role: str | None = None
    notes: str | None = None

    @field_validator("dcs_executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        path = Path(value)
        if path.name.lower() not in {"dcs.exe", "dcs_updater.exe"}:
            raise ValueError("dcs_executable must point to DCS.exe or DCS_updater.exe")
        return str(path)

    @field_validator("extra_arguments")
    @classmethod
    def reject_unsafe_arguments(cls, values: list[str]) -> list[str]:
        for value in values:
            if "\x00" in value or "\n" in value or "\r" in value:
                raise ValueError("launch arguments must be single-line values")
        return values


class DcsLaunchProfile(DcsLaunchProfileCreate):
    profile_id: UUID = Field(default_factory=uuid4)


class DcsLaunchPlan(BaseModel):
    executable: str
    arguments: list[str]
    working_directory: str
    mode: DcsLaunchMode
    mission_path: str | None = None
    runtime_note: str | None = None


class LaunchProfileStore:
    def __init__(self) -> None:
        self._profiles: dict[UUID, DcsLaunchProfile] = {}
        self._lock = RLock()

    def create(self, payload: DcsLaunchProfileCreate) -> DcsLaunchProfile:
        profile = DcsLaunchProfile(**payload.model_dump())
        with self._lock:
            self._profiles[profile.profile_id] = profile
        return profile

    def list(self) -> list[DcsLaunchProfile]:
        with self._lock:
            return list(self._profiles.values())

    def get(self, profile_id: UUID) -> DcsLaunchProfile | None:
        with self._lock:
            return self._profiles.get(profile_id)

    def delete(self, profile_id: UUID) -> bool:
        with self._lock:
            return self._profiles.pop(profile_id, None) is not None


def build_launch_plan(profile: DcsLaunchProfile) -> DcsLaunchPlan:
    executable = Path(profile.dcs_executable)
    arguments: list[str] = []
    runtime_note: str | None = None

    if profile.mode is DcsLaunchMode.OPENXR:
        arguments.extend(["--force_enable_VR", "--force_OpenXR"])
    elif profile.mode is DcsLaunchMode.STEAMVR:
        arguments.append("--force_enable_VR")
        runtime_note = "SteamVR/OpenVR must be selected and ready before DCS starts"

    if profile.mission_path:
        arguments.append(profile.mission_path)

    arguments.extend(profile.extra_arguments)

    return DcsLaunchPlan(
        executable=str(executable),
        arguments=arguments,
        working_directory=str(executable.parent),
        mode=profile.mode,
        mission_path=profile.mission_path,
        runtime_note=runtime_note,
    )


launch_profiles = LaunchProfileStore()
