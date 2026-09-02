from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from orion.srs_process_control import SrsProcessRecord, inspect_windows_processes


ARCHITECTURE_PREFLIGHT_REPORT_ID = "AG-20260902-195734-840e21f7-c8aa825-r1"

GitRunner = Callable[[Path, tuple[str, ...]], str]
ProcessInspector = Callable[[str], Sequence[SrsProcessRecord]]


def run_git(repository: Path, arguments: tuple[str, ...]) -> str:
    result = subprocess.run(
        ["git", *arguments],
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
