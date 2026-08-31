"""Deterministically stamp frozen ORION components with their Git identity."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence

from orion import __version__


_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,160}$")


def write_build_identity_markers(
    *,
    core_dir: Path,
    launcher_dir: Path,
    sha: str,
    branch: str,
    version: str = __version__,
) -> tuple[Path, Path]:
    """Write the same exact marker beside both frozen executables.

    Existing files are deliberately overwritten so an in-place installer cannot
    retain identity metadata from an older ORION build.
    """

    sha_value = sha.strip().lower()
    branch_value = branch.strip()
    version_value = version.strip()
    if _FULL_SHA.fullmatch(sha_value) is None:
        raise ValueError("Build identity packaging requires a full 40-character SHA")
    if _BRANCH.fullmatch(branch_value) is None:
        raise ValueError("Build identity packaging branch is invalid")
    if not version_value or len(version_value) > 80:
        raise ValueError("Build identity packaging version is invalid")

    destinations = (core_dir.resolve(), launcher_dir.resolve())
    for directory in destinations:
        if not directory.is_dir():
            raise FileNotFoundError(f"Frozen component directory is missing: {directory}")

    serialized = json.dumps(
        {
            "sha": sha_value,
            "branch": branch_value,
            "version": version_value,
        },
        indent=2,
        ensure_ascii=True,
    ) + "\n"
    markers: list[Path] = []
    for directory in destinations:
        marker = directory / "build-identity.json"
        marker.write_text(serialized, encoding="utf-8")
        markers.append(marker)
    return markers[0], markers[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-dir", type=Path, required=True)
    parser.add_argument("--launcher-dir", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--version", default=__version__)
    args = parser.parse_args(argv)
    markers = write_build_identity_markers(
        core_dir=args.core_dir,
        launcher_dir=args.launcher_dir,
        sha=args.sha,
        branch=args.branch,
        version=args.version,
    )
    for marker in markers:
        print(marker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
