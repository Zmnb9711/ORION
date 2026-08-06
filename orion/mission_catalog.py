from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class MissionSource(StrEnum):
    USER = "user"
    DCS_INSTALL = "dcs_install"
    CUSTOM = "custom"


class MissionRecord(BaseModel):
    name: str
    path: str
    source: MissionSource
    size_bytes: int = Field(ge=0)
    modified_at: float = Field(ge=0)
    prepared_for_orion: bool = False


@dataclass(frozen=True, slots=True)
class MissionSearchRoot:
    path: Path
    source: MissionSource


def default_search_roots(
    saved_games: Path | None = None,
    dcs_installations: list[Path] | None = None,
) -> list[MissionSearchRoot]:
    roots: list[MissionSearchRoot] = []
    saved_games_root = saved_games or _default_saved_games()

    for variant in ("DCS", "DCS.openbeta"):
        missions = saved_games_root / variant / "Missions"
        roots.append(MissionSearchRoot(missions, MissionSource.USER))

    for installation in dcs_installations or []:
        roots.extend(
            [
                MissionSearchRoot(installation / "Missions", MissionSource.DCS_INSTALL),
                MissionSearchRoot(installation / "Mods" / "campaigns", MissionSource.DCS_INSTALL),
            ]
        )

    return roots


def discover_missions(
    roots: list[MissionSearchRoot],
    custom_directories: list[Path] | None = None,
) -> list[MissionRecord]:
    effective_roots = [*roots]
    for directory in custom_directories or []:
        effective_roots.append(MissionSearchRoot(directory, MissionSource.CUSTOM))

    discovered: dict[Path, MissionRecord] = {}
    for root in effective_roots:
        if not root.path.is_dir():
            continue

        for mission_path in root.path.rglob("*.miz"):
            try:
                resolved = mission_path.resolve()
                stat = resolved.stat()
            except OSError:
                continue

            existing = discovered.get(resolved)
            if existing is not None and _source_priority(existing.source) >= _source_priority(root.source):
                continue

            discovered[resolved] = MissionRecord(
                name=resolved.stem,
                path=str(resolved),
                source=root.source,
                size_bytes=stat.st_size,
                modified_at=stat.st_mtime,
                prepared_for_orion=resolved.stem.endswith(" (ORION)"),
            )

    return sorted(
        discovered.values(),
        key=lambda mission: (mission.source.value, mission.name.casefold(), mission.path.casefold()),
    )


def _default_saved_games() -> Path:
    user_profile = os.getenv("USERPROFILE")
    if user_profile:
        return Path(user_profile) / "Saved Games"
    return Path.home() / "Saved Games"


def _source_priority(source: MissionSource) -> int:
    return {
        MissionSource.DCS_INSTALL: 1,
        MissionSource.CUSTOM: 2,
        MissionSource.USER: 3,
    }[source]
