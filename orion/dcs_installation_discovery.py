from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from orion.dcs_installations import DcsInstallationType
from orion.dcs_readiness import discover_saved_games
from orion.dcs_steam_detection import discover_steam_dcs


class DcsDiscoveryCandidate(BaseModel):
    installation_type: DcsInstallationType
    name: str
    install_root: str
    executable_path: str
    saved_games_candidates: list[str] = Field(default_factory=list)
    exists: bool = False
    source_detail: str | None = None


class DcsDiscoveryResult(BaseModel):
    mode: DcsInstallationType
    candidates: list[DcsDiscoveryCandidate] = Field(default_factory=list)


def discover_dcs_installations(
    mode: DcsInstallationType = DcsInstallationType.AUTO,
    *,
    steam_roots: list[Path] | None = None,
    standalone_roots: list[Path] | None = None,
) -> DcsDiscoveryResult:
    candidates: list[DcsDiscoveryCandidate] = []

    if mode in {DcsInstallationType.AUTO, DcsInstallationType.STEAM}:
        for item in discover_steam_dcs(steam_roots=steam_roots):
            candidates.append(
                DcsDiscoveryCandidate(
                    installation_type=DcsInstallationType.STEAM,
                    name="DCS Steam",
                    install_root=item.install_root,
                    executable_path=item.executable_path,
                    saved_games_candidates=item.saved_games_candidates,
                    exists=item.executable_exists,
                    source_detail=item.steam_library,
                )
            )

    if mode in {DcsInstallationType.AUTO, DcsInstallationType.STANDALONE}:
        roots = standalone_roots if standalone_roots is not None else _default_standalone_roots()
        for root in roots:
            candidate = candidate_from_install_root(root, DcsInstallationType.STANDALONE, source_detail="Eagle Dynamics")
            if candidate is not None:
                candidates.append(candidate)

    return DcsDiscoveryResult(mode=mode, candidates=_dedupe(candidates))


def candidate_from_install_root(
    root: Path,
    installation_type: DcsInstallationType = DcsInstallationType.STANDALONE,
    *,
    source_detail: str = "Manual selection",
) -> DcsDiscoveryCandidate | None:
    """Validate a user-selected DCS root (or bin/bin-mt folder) without guessing success."""
    root = root.expanduser()
    if root.name.casefold() in {"bin", "bin-mt"} and (root / "DCS.exe").is_file():
        root = root.parent
    executable = _find_dcs_executable(root)
    if not root.is_dir() or not executable.is_file():
        return None
    return DcsDiscoveryCandidate(
        installation_type=installation_type,
        name="DCS Steam" if installation_type == DcsInstallationType.STEAM else "DCS Standalone",
        install_root=str(root),
        executable_path=str(executable),
        saved_games_candidates=[item.path for item in discover_saved_games()],
        exists=True,
        source_detail=source_detail,
    )


def _find_dcs_executable(root: Path) -> Path:
    # Modern DCS may expose either launcher layout. Accept both and prefer bin-mt.
    mt = root / "bin-mt" / "DCS.exe"
    if mt.is_file():
        return mt
    classic = root / "bin" / "DCS.exe"
    if classic.is_file():
        return classic
    return mt


def _default_standalone_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            roots.append(path)

    # Standard ED locations.
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_name)
        if base:
            eagle = Path(base) / "Eagle Dynamics"
            add(eagle / "DCS World")
            add(eagle / "DCS World OpenBeta")

    # DCS is commonly installed on a dedicated Windows drive. Probe only the
    # conventional ED roots; never recursively scan user disks.
    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            if not drive.exists():
                continue
            for prefix in (drive, drive / "Games", drive / "Program Files"):
                eagle = prefix / "Eagle Dynamics"
                add(eagle / "DCS World")
                add(eagle / "DCS World OpenBeta")

    return roots


def _dedupe(items: list[DcsDiscoveryCandidate]) -> list[DcsDiscoveryCandidate]:
    result: list[DcsDiscoveryCandidate] = []
    seen: set[str] = set()
    for item in items:
        key = item.executable_path.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
