from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from orion.srs_process_control import SrsProcessRecord, inspect_windows_processes


ARCHITECTURE_PREFLIGHT_REPORT_ID = "AG-20260902-205236-989bb053-f5c4fa9-r1"

GitRunner = Callable[[Path, tuple[str, ...]], str]
ProcessInspector = Callable[[str], Sequence[SrsProcessRecord]]


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", path.parents[4].name))


def resolve_git_executable(environment: Mapping[str, str] | None = None) -> Path:
    """Resolve an existing Git without repairing or mutating the host environment."""

    values = dict(os.environ if environment is None else environment)
    on_path = shutil.which("git", path=values.get("PATH", ""))
    if on_path:
        return Path(on_path).resolve()

    candidates: list[Path] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        root = values.get(key)
        if root:
            candidates.append(Path(root) / "Git" / "cmd" / "git.exe")

    local_app_data = values.get("LOCALAPPDATA")
    if local_app_data:
        desktop_root = Path(local_app_data) / "GitHubDesktop"
        desktop_candidates = sorted(
            desktop_root.glob("app-*/resources/app/git/cmd/git.exe"),
            key=_version_key,
            reverse=True,
        )
        candidates.extend(desktop_candidates)

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Git executable is unavailable in PATH or supported Windows installations")


def run_git(repository: Path, arguments: tuple[str, ...]) -> str:
    executable = resolve_git_executable()
    result = subprocess.run(
        [str(executable), *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class VerificationContext:
    repository_root: Path
    local_app_data: Path
    guard_root: Path
    console_root: Path
    architecture_report_id: str = ARCHITECTURE_PREFLIGHT_REPORT_ID
    saved_games_root: Path | None = None
    dcs_steam_roots: list[Path] | None = None
    dcs_standalone_roots: list[Path] | None = None
    installation_candidates: tuple[Path, ...] | None = None
    installer_metadata: Mapping[str, str] | None = None
    srs_environment: Mapping[str, str] | None = None
    git_runner: GitRunner = run_git
    process_inspector: ProcessInspector = inspect_windows_processes
    now: Callable[[], datetime] = utc_now
    environment: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))

    @classmethod
    def defaults(cls, repository_root: Path) -> VerificationContext:
        home = Path.home()
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        guard = local / "ORION" / "development" / "architecture-guard"
        console = local / "ORION" / "development" / "console"
        return cls(
            repository_root=repository_root.expanduser().resolve(),
            local_app_data=local,
            guard_root=guard,
            console_root=console,
        )
