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
        for root in standalone_roots or _default_standalone_roots():
            executable = _find_dcs_executable(root)
            if not root.exists():
                continue
            candidates.append(
                DcsDiscoveryCandidate(
                    installation_type=DcsInstallationType.STANDALONE,
                    name="DCS Standalone",
                    install_root=str(root),
                    executable_path=str(executable),
                    saved_games_candidates=[item.path for item in discover_saved_games()],
                    exists=executable.is_file(),
                    source_detail="Eagle Dynamics",
                )
            )

    return DcsDiscoveryResult(mode=mode, candidates=_dedupe(candidates))


def _find_dcs_executable(root: Path) -> Path:
    preferred = root / "bin" / "DCS.exe"
    if preferred.is_file():
        return preferred
    mt = root / "bin-mt" / "DCS.exe"
    if mt.is_file():
        return mt
    return preferred


def _default_standalone_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_name)
        if not base:
            continue
        eagle = Path(base) / "Eagle Dynamics"
        roots.extend(
            [
                eagle / "DCS World",
                eagle / "DCS World OpenBeta",
            ]
        )
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
