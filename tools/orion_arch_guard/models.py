from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class SourceType(StrEnum):
    CHATGPT_ARCHIVE = "chatgpt_archive"
    CHATGPT_ARCHIVE_ROOT = "chatgpt_archive_root"
    CODEX_ROLLOUT = "codex_rollout"
    CODEX_HISTORY_ROOT = "codex_history_root"
    GIT_REPOSITORY = "git_repository"
    EVIDENCE_ZIP = "evidence_zip"
    EVIDENCE_ROOT = "evidence_root"
    RELEASE_TREE = "release_tree"
    RELEASE_ROOT = "release_root"
    RUNTIME_ARTIFACT = "runtime_artifact"
    RUNTIME_ROOT = "runtime_root"
    PROJECT_DOCUMENT = "project_document"


class PrivacyClass(StrEnum):
    PRIVATE_PRIMARY_HISTORY = "PRIVATE_PRIMARY_HISTORY"
    PRIVATE_EVIDENCE = "PRIVATE_EVIDENCE"
    PRIVATE_RUNTIME_LOG = "PRIVATE_RUNTIME_LOG"
    PROJECT_GIT = "PROJECT_GIT"
    PUBLIC_OR_NON_SENSITIVE = "PUBLIC_OR_NON_SENSITIVE"
    GENERATED_GUARD_METADATA = "GENERATED_GUARD_METADATA"


class ChangeStatus(StrEnum):
    UNCHANGED = "UNCHANGED"
    CHANGED = "CHANGED"
    MISSING = "MISSING"
    NEW = "NEW"
    RELOCATED = "RELOCATED"


Metadata = dict[str, bool | float | int | str | list[str] | None]


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    source_type: SourceType
    path: str
    exists: bool
    size_bytes: int | None
    sha256: str | None
    mtime_utc: str | None
    format: str
    privacy_class: PrivacyClass
    discovery_method: str
    metadata: Metadata = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SourceRecord:
        return cls(
            source_id=str(payload["source_id"]),
            source_type=SourceType(payload["source_type"]),
            path=str(payload["path"]),
            exists=bool(payload["exists"]),
            size_bytes=payload.get("size_bytes"),
            sha256=payload.get("sha256"),
            mtime_utc=payload.get("mtime_utc"),
            format=str(payload["format"]),
            privacy_class=PrivacyClass(payload["privacy_class"]),
            discovery_method=str(payload["discovery_method"]),
            metadata=dict(payload.get("metadata", {})),
            error=payload.get("error"),
        )

    @property
    def path_key(self) -> tuple[SourceType, str]:
        return self.source_type, str(Path(self.path)).casefold()


@dataclass(frozen=True, slots=True)
class SourceChange:
    status: ChangeStatus
    source_type: SourceType
    source_id: str
    old_path: str | None
    new_path: str | None
    old_sha256: str | None
    new_sha256: str | None


@dataclass(frozen=True, slots=True)
class Manifest:
    schema_version: int
    tool_version: str
    generated_at_utc: str
    repository_root: str
    discovery_config: dict[str, Any]
    sources: tuple[SourceRecord, ...]
    previous_manifest_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "generated_at_utc": self.generated_at_utc,
            "repository_root": self.repository_root,
            "discovery_config": self.discovery_config,
            "previous_manifest_sha256": self.previous_manifest_sha256,
            "sources": [source.to_dict() for source in self.sources],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Manifest:
        return cls(
            schema_version=int(payload["schema_version"]),
            tool_version=str(payload["tool_version"]),
            generated_at_utc=str(payload["generated_at_utc"]),
            repository_root=str(payload["repository_root"]),
            discovery_config=dict(payload["discovery_config"]),
            previous_manifest_sha256=payload.get("previous_manifest_sha256"),
            sources=tuple(
                SourceRecord.from_dict(item) for item in payload.get("sources", [])
            ),
        )
