from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in paths:
        expanded = candidate.expanduser().absolute()
        key = str(expanded).casefold()
        if key not in seen:
            result.append(expanded)
            seen.add(key)
    return tuple(result)


def _find_repository_root(start: Path) -> Path:
    candidate = start.absolute()
    for parent in (candidate, *candidate.parents):
        if (parent / ".git").exists():
            return parent
    return candidate


@dataclass(frozen=True, slots=True)
class SourceConfig:
    repository_root: Path
    output_path: Path
    chatgpt_archive_roots: tuple[Path, ...]
    codex_history_roots: tuple[Path, ...]
    evidence_roots: tuple[Path, ...]
    runtime_log_roots: tuple[Path, ...]
    release_roots: tuple[Path, ...]

    @classmethod
    def defaults(cls, repository_root: Path | None = None) -> SourceConfig:
        repo = _find_repository_root(repository_root or Path.cwd())
        user_home = Path.home()
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA", user_home / "AppData" / "Local")
        )
        codex_home = Path(os.environ.get("CODEX_HOME", user_home / ".codex"))
        guard_root = local_app_data / "ORION" / "development" / "architecture-guard"
        orion_runtime = local_app_data / "ORION" / "runtime"
        return cls(
            repository_root=repo,
            output_path=guard_root / "source-manifest.json",
            chatgpt_archive_roots=(user_home / "Downloads",),
            codex_history_roots=(codex_home / "sessions",),
            evidence_roots=(orion_runtime / "test-evidence",),
            runtime_log_roots=(orion_runtime, repo / "runtime"),
            release_roots=(repo,),
        )

    @classmethod
    def from_json(
        cls, path: Path, repository_root: Path | None = None
    ) -> SourceConfig:
        payload = json.loads(path.read_text(encoding="utf-8"))
        base = cls.defaults(repository_root)
        return cls.from_mapping(payload, base=base)

    @classmethod
    def from_mapping(
        cls, payload: dict[str, Any], *, base: SourceConfig | None = None
    ) -> SourceConfig:
        current = base or cls.defaults()

        def paths(name: str, fallback: tuple[Path, ...]) -> tuple[Path, ...]:
            raw = payload.get(name)
            if raw is None:
                return fallback
            if not isinstance(raw, list):
                raise ValueError(f"{name} must be an array of paths")
            return _unique_paths(Path(str(item)) for item in raw)

        repository = Path(
            str(payload.get("repository_root", current.repository_root))
        ).expanduser().absolute()
        output = Path(str(payload.get("output_path", current.output_path))).expanduser()
        return cls(
            repository_root=repository,
            output_path=output.absolute(),
            chatgpt_archive_roots=paths(
                "chatgpt_archive_roots", current.chatgpt_archive_roots
            ),
            codex_history_roots=paths(
                "codex_history_roots", current.codex_history_roots
            ),
            evidence_roots=paths("evidence_roots", current.evidence_roots),
            runtime_log_roots=paths(
                "runtime_log_roots", current.runtime_log_roots
            ),
            release_roots=paths("release_roots", current.release_roots),
        )

    def with_overrides(
        self,
        *,
        repository_root: Path | None = None,
        output_path: Path | None = None,
        chatgpt_archive_roots: tuple[Path, ...] | None = None,
    ) -> SourceConfig:
        return replace(
            self,
            repository_root=(
                repository_root.absolute()
                if repository_root is not None
                else self.repository_root
            ),
            output_path=(
                output_path.absolute() if output_path is not None else self.output_path
            ),
            chatgpt_archive_roots=(
                _unique_paths(chatgpt_archive_roots)
                if chatgpt_archive_roots is not None
                else self.chatgpt_archive_roots
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_root": str(self.repository_root),
            "output_path": str(self.output_path),
            "chatgpt_archive_roots": [str(path) for path in self.chatgpt_archive_roots],
            "codex_history_roots": [str(path) for path in self.codex_history_roots],
            "evidence_roots": [str(path) for path in self.evidence_roots],
            "runtime_log_roots": [str(path) for path in self.runtime_log_roots],
            "release_roots": [str(path) for path in self.release_roots],
        }
