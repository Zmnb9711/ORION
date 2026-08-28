"""Privacy-safe build identity for source and frozen ORION runtimes."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from orion import __version__


_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,160}$")


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    sha: str
    branch: str
    version: str
    source: str


def load_build_identity() -> BuildIdentity:
    """Resolve a bounded identity without invoking Git or exposing configuration."""

    environment = _validated(
        os.environ.get("ORION_BUILD_SHA"),
        os.environ.get("ORION_BUILD_BRANCH"),
        os.environ.get("ORION_BUILD_VERSION"),
        source="environment",
    )
    if environment is not None:
        return environment

    for marker in _marker_candidates():
        identity = _read_marker(marker)
        if identity is not None:
            return identity

    source = _read_source_git_identity(Path(__file__).resolve())
    if source is not None:
        return source
    return BuildIdentity("unknown", "unknown", __version__, "unavailable")


def _marker_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        candidates.extend(
            (
                executable.parent / "build-identity.json",
                executable.parent.parent / "build-identity.json",
            )
        )
    candidates.append(Path(__file__).resolve().parent / "build-identity.json")
    return tuple(dict.fromkeys(candidates))


def _read_marker(path: Path) -> BuildIdentity | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _validated(
        payload.get("sha"),
        payload.get("branch"),
        payload.get("version"),
        source="frozen_marker",
    )


def _read_source_git_identity(start: Path) -> BuildIdentity | None:
    for parent in start.parents:
        git = parent / ".git"
        if not git.is_dir():
            continue
        try:
            head = (git / "HEAD").read_text(encoding="utf-8").strip()
            if head.startswith("ref: "):
                reference = head.removeprefix("ref: ").strip()
                ref_path = git / reference
                sha = ref_path.read_text(encoding="utf-8").strip()
                branch = reference.removeprefix("refs/heads/")
            else:
                sha = head
                branch = "detached"
        except OSError:
            return None
        return _validated(sha, branch, __version__, source="source_git")
    return None


def _validated(
    sha: object,
    branch: object,
    version: object,
    *,
    source: str,
) -> BuildIdentity | None:
    sha_value = str(sha or "").strip()
    branch_value = str(branch or "").strip()
    version_value = str(version or __version__).strip()
    if _SHA.fullmatch(sha_value) is None or _BRANCH.fullmatch(branch_value) is None:
        return None
    if not version_value or len(version_value) > 80:
        version_value = __version__
    return BuildIdentity(
        sha=sha_value.lower(),
        branch=branch_value,
        version=version_value,
        source=source,
    )
