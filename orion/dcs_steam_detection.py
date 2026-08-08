from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import BaseModel, Field

from orion.dcs_installations import DcsInstallationType
from orion.dcs_readiness import discover_saved_games


DCS_STEAM_APP_ID = "223750"


class SteamDcsCandidate(BaseModel):
    installation_type: DcsInstallationType = DcsInstallationType.STEAM
    steam_library: str
    install_root: str
    executable_path: str
    manifest_path: str | None = None
    saved_games_candidates: list[str] = Field(default_factory=list)
    executable_exists: bool = False


def discover_steam_dcs(steam_roots: list[Path] | None = None) -> list[SteamDcsCandidate]:
    candidates: list[SteamDcsCandidate] = []
    seen: set[str] = set()
    for steam_root in steam_roots or _default_steam_roots():
        for library in _steam_libraries(steam_root):
            steamapps = library / "steamapps"
            manifest = steamapps / f"appmanifest_{DCS_STEAM_APP_ID}.acf"
            install_dir = _manifest_install_dir(manifest) if manifest.is_file() else None
            roots: list[Path] = []
            if install_dir:
                roots.append(steamapps / "common" / install_dir)
            roots.append(steamapps / "common" / "DCSWorld")
            for install_root in roots:
                executable = _find_dcs_executable(install_root)
                key = str(executable).casefold()
                if key in seen or not install_root.exists():
                    continue
                seen.add(key)
                candidates.append(
                    SteamDcsCandidate(
                        steam_library=str(library),
                        install_root=str(install_root),
                        executable_path=str(executable),
                        manifest_path=str(manifest) if manifest.is_file() else None,
                        saved_games_candidates=[item.path for item in discover_saved_games()],
                        executable_exists=executable.is_file(),
                    )
                )
    return candidates


def _find_dcs_executable(install_root: Path) -> Path:
    preferred = install_root / "bin" / "DCS.exe"
    if preferred.is_file():
        return preferred
    mt = install_root / "bin-mt" / "DCS.exe"
    if mt.is_file():
        return mt
    return preferred


def _manifest_install_dir(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r'"installdir"\s+"([^"]+)"', text, re.IGNORECASE)
    return match.group(1) if match else None


def _steam_libraries(root: Path) -> list[Path]:
    libraries = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if not vdf.is_file():
        return libraries
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return libraries
    for raw in re.findall(r'"path"\s+"([^"]+)"', text, re.IGNORECASE):
        path = Path(raw.replace("\\\\", "\\"))
        if path not in libraries:
            libraries.append(path)
    return libraries


def _default_steam_roots() -> list[Path]:
    roots: list[Path] = []
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    program_files = os.environ.get("PROGRAMFILES")
    for base in (program_files_x86, program_files):
        if base:
            candidate = Path(base) / "Steam"
            if candidate not in roots:
                roots.append(candidate)
    return roots
