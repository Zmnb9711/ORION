from __future__ import annotations

from enum import StrEnum
from pathlib import Path, PureWindowsPath
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class DcsInstallationSource(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class DcsInstallationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    executable_path: str
    source: DcsInstallationSource = DcsInstallationSource.MANUAL

    @field_validator("executable_path")
    @classmethod
    def validate_executable_name(cls, value: str) -> str:
        windows_name = PureWindowsPath(value).name.lower()
        native_name = Path(value).name.lower()
        if windows_name not in {"dcs.exe", "dcs_updater.exe"} and native_name not in {
            "dcs.exe",
            "dcs_updater.exe",
        }:
            raise ValueError("executable_path must point to DCS.exe or DCS_updater.exe")
        return value


class DcsInstallationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    executable_path: str | None = None

    @field_validator("executable_path")
    @classmethod
    def validate_executable_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        windows_name = PureWindowsPath(value).name.lower()
        native_name = Path(value).name.lower()
        if windows_name not in {"dcs.exe", "dcs_updater.exe"} and native_name not in {
            "dcs.exe",
            "dcs_updater.exe",
        }:
            raise ValueError("executable_path must point to DCS.exe or DCS_updater.exe")
        return value


class DcsInstallation(DcsInstallationCreate):
    installation_id: UUID = Field(default_factory=uuid4)
    exists: bool


class DcsInstallationStore:
    def __init__(self) -> None:
        self._items: dict[UUID, DcsInstallation] = {}
        self._lock = RLock()

    def create(self, payload: DcsInstallationCreate) -> DcsInstallation:
        item = DcsInstallation(
            **payload.model_dump(),
            exists=Path(payload.executable_path).is_file(),
        )
        with self._lock:
            self._items[item.installation_id] = item
        return item

    def list(self) -> list[DcsInstallation]:
        with self._lock:
            return list(self._items.values())

    def get(self, installation_id: UUID) -> DcsInstallation | None:
        with self._lock:
            return self._items.get(installation_id)

    def update(
        self, installation_id: UUID, payload: DcsInstallationUpdate
    ) -> DcsInstallation | None:
        with self._lock:
            current = self._items.get(installation_id)
            if current is None:
                return None
            changes = payload.model_dump(exclude_none=True)
            executable_path = changes.get("executable_path", current.executable_path)
            changes["exists"] = Path(executable_path).is_file()
            updated = current.model_copy(update=changes)
            self._items[installation_id] = updated
            return updated

    def delete(self, installation_id: UUID) -> bool:
        with self._lock:
            return self._items.pop(installation_id, None) is not None

    def refresh(self, installation_id: UUID) -> DcsInstallation | None:
        with self._lock:
            current = self._items.get(installation_id)
            if current is None:
                return None
            refreshed = current.model_copy(
                update={"exists": Path(current.executable_path).is_file()}
            )
            self._items[installation_id] = refreshed
            return refreshed


dcs_installations = DcsInstallationStore()
