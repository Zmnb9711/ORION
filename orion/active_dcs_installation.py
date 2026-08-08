from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from pydantic import BaseModel

from orion.dcs_installations import DcsInstallationType


class ActiveDcsInstallation(BaseModel):
    installation_type: DcsInstallationType
    executable_path: str
    install_root: str | None = None
    saved_games_path: str | None = None
    display_name: str | None = None


class ActiveDcsInstallationStore:
    """Persists the DCS installation explicitly selected by the user."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_config_path()
        self._lock = RLock()

    def get(self) -> ActiveDcsInstallation | None:
        with self._lock:
            if not self._path.is_file():
                return None
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
                return ActiveDcsInstallation.model_validate(payload)
            except (OSError, ValueError, json.JSONDecodeError):
                return None

    def set(self, selection: ActiveDcsInstallation) -> ActiveDcsInstallation:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(self._path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(selection.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self._path)
            return selection.model_copy(deep=True)

    def clear(self) -> None:
        with self._lock:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass


def _default_config_path() -> Path:
    override = os.environ.get("ORION_CONFIG_DIR")
    if override:
        return Path(override) / "active-dcs.json"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "ORION" / "active-dcs.json"
    return Path.home() / ".orion" / "active-dcs.json"


active_dcs_installation = ActiveDcsInstallationStore()
