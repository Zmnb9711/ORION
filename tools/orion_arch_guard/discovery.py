from __future__ import annotations

import json
import os
import re
import subprocess
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.orion_arch_guard.config import SourceConfig
from tools.orion_arch_guard.fingerprints import (
    bounded_directory_record,
    canonical_sha256,
    file_record,
    missing_record,
    mtime_utc,
    sha256_file,
    stable_locator_source_id,
)
from tools.orion_arch_guard.models import PrivacyClass, SourceRecord, SourceType

KNOWN_CHATGPT_ARCHIVE_SHA256 = (
    "EDD800F61210C6C682414E960C1A54D62DBBCC6DEED27B7FDF741DC5499937DB"
)
KNOWN_CHATGPT_ARCHIVE_SIZE = 233_063_533
KNOWN_CHATGPT_CONVERSATION_COUNT = 42
ESTABLISHED_ORION_CONVERSATION_COUNT = 26
ESTABLISHED_ORION_MESSAGE_COUNT = 6_602

_SHA_RE = re.compile(r"\b[0-9a-fA-F]{40}\b")
_SAFE_SESSION_RE = re.compile(r"[0-9a-fA-F-]{16,64}")
_LOG_SUFFIXES = {".json", ".jsonl", ".log", ".txt"}
_MAX_ZIP_METADATA_BYTES = 256 * 1024
_MAX_RELEASE_ENTRIES = 512


def _root_record(
    path: Path,
    *,
    source_type: SourceType,
    privacy_class: PrivacyClass,
    discovery_method: str,
    children: Iterable[SourceRecord],
) -> SourceRecord:
    child_list = list(children)
    if not path.is_dir():
        return missing_record(
            path,
            source_type=source_type,
            privacy_class=privacy_class,
            discovery_method=discovery_method,
            error="configured source root is unavailable",
        )
    child_identity = sorted(
        f"{item.source_type.value}|{item.source_id}|{Path(item.path).name}"
        for item in child_list
    )
    return SourceRecord(
        source_id=stable_locator_source_id(
            source_type, path.name or source_type.value, discovery_method
        ),
        source_type=source_type,
        path=str(path.absolute()),
        exists=True,
        size_bytes=None,
        sha256=canonical_sha256(child_identity),
        mtime_utc=mtime_utc(path),
        format="directory/source-root",
        privacy_class=privacy_class,
        discovery_method=discovery_method,
        metadata={"discovered_child_count": len(child_list)},
    )


def _chatgpt_metadata(path: Path) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "conversations.json" not in names:
                return None
            with archive.open("conversations.json") as raw:
                conversation_count = len(json.load(raw))
            return {
                "archive_entry_count": len(names),
                "conversation_count_mechanical": conversation_count,
                "mechanical_count_semantics": "all_export_conversations",
            }
    except (OSError, ValueError, zipfile.BadZipFile):
        return None


def discover_chatgpt_archives(config: SourceConfig) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for root in config.chatgpt_archive_roots:
        children: list[SourceRecord] = []
        if root.is_dir():
            for candidate in sorted(root.rglob("*.zip")):
                metadata = _chatgpt_metadata(candidate)
                if metadata is None:
                    continue
                record = file_record(
                    candidate,
                    source_type=SourceType.CHATGPT_ARCHIVE,
                    privacy_class=PrivacyClass.PRIVATE_PRIMARY_HISTORY,
                    discovery_method="configured_chatgpt_archive_root",
                    format_name="chatgpt-export/zip",
                    metadata=metadata,
                )
                if record.sha256 == KNOWN_CHATGPT_ARCHIVE_SHA256:
                    known_match = (
                        record.size_bytes == KNOWN_CHATGPT_ARCHIVE_SIZE
                        and metadata["conversation_count_mechanical"]
                        == KNOWN_CHATGPT_CONVERSATION_COUNT
                    )
                    record = replace(
                        record,
                        metadata={
                            **record.metadata,
                            "known_orion_archive_fingerprint_match": known_match,
                            "established_orion_conversation_count": (
                                ESTABLISHED_ORION_CONVERSATION_COUNT
                            ),
                            "established_principal_orion_message_count": (
                                ESTABLISHED_ORION_MESSAGE_COUNT
                            ),
                            "established_counts_semantics": (
                                "prior_chronological_reconstruction_not_keyword_count"
                            ),
                        },
                    )
                children.append(record)
        records.extend(children)
        records.append(
            _root_record(
                root,
                source_type=SourceType.CHATGPT_ARCHIVE_ROOT,
                privacy_class=PrivacyClass.PRIVATE_PRIMARY_HISTORY,
                discovery_method="configured_chatgpt_archive_root",
                children=children,
            )
        )
    return records


def discover_codex_history(config: SourceConfig) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for root in config.codex_history_roots:
        children: list[SourceRecord] = []
        if root.is_dir():
            for candidate in sorted(root.rglob("*.jsonl")):
                children.append(
                    file_record(
                        candidate,
                        source_type=SourceType.CODEX_ROLLOUT,
                        privacy_class=PrivacyClass.PRIVATE_PRIMARY_HISTORY,
                        discovery_method="configured_codex_history_root",
                        format_name="codex-rollout/jsonl",
                        metadata={"coverage": "PARTIAL"},
                    )
                )
        records.extend(children)
        records.append(
            _root_record(
                root,
                source_type=SourceType.CODEX_HISTORY_ROOT,
                privacy_class=PrivacyClass.PRIVATE_PRIMARY_HISTORY,
                discovery_method="configured_codex_history_root",
                children=children,
            )
        )
    return records


def _read_bounded_zip_text(
    archive: zipfile.ZipFile, names: Iterable[str]
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    by_basename = {Path(name).name.casefold(): name for name in archive.namelist()}
    for requested in names:
        archive_name = by_basename.get(requested.casefold())
        if archive_name is None:
            continue
        with archive.open(archive_name) as stream:
            value = stream.read(_MAX_ZIP_METADATA_BYTES).decode("utf-8", errors="replace")
        result.append((archive_name, value))
    return result


def _safe_key_value(
    text: str, keys: tuple[str, ...], value_pattern: re.Pattern[str]
) -> str | None:
    key_expression = "|".join(re.escape(key) for key in keys)
    pattern = re.compile(
        rf"(?:{key_expression})\s*[=:]\s*[\"']?({value_pattern.pattern})",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def _evidence_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            metadata["archive_entry_count"] = len(archive.infolist())
            metadata["metadata_entries_checked"] = []
            for name, text in _read_bounded_zip_text(
                archive,
                ("manifest.txt", "session-summary.txt", "timing-summary.txt"),
            ):
                cast_names = metadata["metadata_entries_checked"]
                if isinstance(cast_names, list):
                    cast_names.append(Path(name).name)
                lowered = text.casefold()
                if "orion_build_sha" in lowered or "build_sha" in lowered:
                    sha = _safe_key_value(
                        text, ("orion_build_sha", "build_sha"), _SHA_RE
                    )
                    if sha:
                        metadata.setdefault("build_sha", sha.casefold())
                if "test_session_id" in lowered or "session_id" in lowered:
                    session_id = _safe_key_value(
                        text, ("test_session_id", "session_id"), _SAFE_SESSION_RE
                    )
                    if session_id:
                        metadata.setdefault("session_identity", session_id)
                kind = _safe_key_value(
                    text,
                    ("evidence_type", "session_type", "test_type"),
                    re.compile(r"FIELD|PROBE", re.IGNORECASE),
                )
                if kind:
                    metadata.setdefault("explicit_evidence_kind", kind.upper())
    except (OSError, zipfile.BadZipFile):
        metadata["bounded_metadata_status"] = "unreadable"
    return metadata


def discover_evidence(config: SourceConfig) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for root in config.evidence_roots:
        children: list[SourceRecord] = []
        if root.is_dir():
            for candidate in sorted(root.rglob("*.zip")):
                if not candidate.name.casefold().startswith("orion-test-evidence-"):
                    continue
                children.append(
                    file_record(
                        candidate,
                        source_type=SourceType.EVIDENCE_ZIP,
                        privacy_class=PrivacyClass.PRIVATE_EVIDENCE,
                        discovery_method="configured_evidence_root",
                        format_name="orion-test-evidence/zip",
                        metadata=_evidence_metadata(candidate),
                    )
                )
        records.extend(children)
        records.append(
            _root_record(
                root,
                source_type=SourceType.EVIDENCE_ROOT,
                privacy_class=PrivacyClass.PRIVATE_EVIDENCE,
                discovery_method="configured_evidence_root",
                children=children,
            )
        )
    return records


def _release_candidates(path: Path) -> list[Path]:
    selected: dict[str, Path] = {}
    for pattern in ("*.exe", "*.msi", "*.zip", "build-identity.json"):
        for candidate in path.glob(pattern):
            if candidate.is_file():
                selected[str(candidate.absolute()).casefold()] = candidate
    for candidate in path.rglob("build-identity.json"):
        if candidate.is_file():
            selected[str(candidate.absolute()).casefold()] = candidate
        if len(selected) >= _MAX_RELEASE_ENTRIES:
            break
    return sorted(selected.values())[:_MAX_RELEASE_ENTRIES]


def _release_build_sha(candidates: Iterable[Path]) -> str | None:
    for candidate in candidates:
        if candidate.name.casefold() != "build-identity.json":
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            value = str(payload.get("sha", ""))
            if _SHA_RE.fullmatch(value):
                return value.casefold()
        except (OSError, ValueError):
            continue
    return None


def discover_releases(config: SourceConfig) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for root in config.release_roots:
        release_directories: list[Path] = []
        if root.is_dir():
            if root.name.casefold().startswith("release-"):
                release_directories = [root]
            else:
                release_directories = sorted(
                    path
                    for path in root.glob("release-*")
                    if path.is_dir()
                )
        children: list[SourceRecord] = []
        for release in release_directories:
            candidates = _release_candidates(release)
            entries: list[dict[str, Any]] = []
            for candidate in candidates:
                relative = candidate.relative_to(release).as_posix()
                entry: dict[str, Any] = {
                    "path": relative,
                    "size_bytes": candidate.stat().st_size,
                    "mtime_utc": mtime_utc(candidate),
                }
                if candidate.name.casefold() == "build-identity.json":
                    entry["sha256"] = sha256_file(candidate)
                entries.append(entry)
            children.append(
                bounded_directory_record(
                    release,
                    source_type=SourceType.RELEASE_TREE,
                    privacy_class=PrivacyClass.PROJECT_GIT,
                    discovery_method="release_tree_bounded_manifest",
                    entries=entries,
                    metadata={
                        "release_name": release.name,
                        "selected_artifact_count": len(entries),
                        "entry_limit": _MAX_RELEASE_ENTRIES,
                        "build_sha": _release_build_sha(candidates),
                        "fingerprint_semantics": (
                            "top_level_installers_archives_and_build_identity_markers"
                        ),
                    },
                )
            )
        records.extend(children)
        records.append(
            _root_record(
                root,
                source_type=SourceType.RELEASE_ROOT,
                privacy_class=PrivacyClass.PROJECT_GIT,
                discovery_method="configured_release_root",
                children=children,
            )
        )
    return records


def discover_runtime_artifacts(config: SourceConfig) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    seen_paths: set[str] = set()
    for root in config.runtime_log_roots:
        children: list[SourceRecord] = []
        if root.is_dir():
            for candidate in sorted(root.rglob("*")):
                key = str(candidate.absolute()).casefold()
                if (
                    not candidate.is_file()
                    or candidate.suffix.casefold() not in _LOG_SUFFIXES
                    or key in seen_paths
                ):
                    continue
                seen_paths.add(key)
                children.append(
                    file_record(
                        candidate,
                        source_type=SourceType.RUNTIME_ARTIFACT,
                        privacy_class=PrivacyClass.PRIVATE_RUNTIME_LOG,
                        discovery_method="configured_runtime_log_root",
                        format_name=f"runtime/{candidate.suffix.removeprefix('.').casefold()}",
                        metadata={},
                    )
                )
        records.extend(children)
        records.append(
            _root_record(
                root,
                source_type=SourceType.RUNTIME_ROOT,
                privacy_class=PrivacyClass.PRIVATE_RUNTIME_LOG,
                discovery_method="configured_runtime_log_root",
                children=children,
            )
        )
    return records


def _git(
    repository_root: Path, *args: str, check: bool = True
) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.stdout.strip()


def discover_git(config: SourceConfig) -> SourceRecord:
    root = config.repository_root
    if not (root / ".git").exists():
        return missing_record(
            root,
            source_type=SourceType.GIT_REPOSITORY,
            privacy_class=PrivacyClass.PROJECT_GIT,
            discovery_method="git_cli",
            error="repository .git directory is unavailable",
        )
    try:
        head = _git(root, "rev-parse", "HEAD")
        branch = _git(root, "branch", "--show-current")
        upstream = _git(
            root,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
            check=False,
        )
        origin_sha = _git(root, "rev-parse", upstream, check=False) if upstream else ""
        divergence = (
            _git(root, "rev-list", "--left-right", "--count", f"HEAD...{upstream}", check=False)
            if upstream
            else ""
        )
        refs = _git(root, "show-ref", check=False).splitlines()
        refs_fingerprint = canonical_sha256(sorted(refs))
        status_lines = _git(root, "status", "--short").splitlines()
        tracked_changes = sum(not line.startswith("??") for line in status_lines)
        untracked = sum(line.startswith("??") for line in status_lines)
        staged = len(_git(root, "diff", "--cached", "--name-only").splitlines())
        tracked_diff_sha256 = canonical_sha256(_git(root, "diff", "--binary"))
        staged_diff_sha256 = canonical_sha256(
            _git(root, "diff", "--cached", "--binary")
        )
        deleted_paths = {
            line
            for line in _git(
                root,
                "log",
                "--all",
                "--format=",
                "--name-only",
                "--diff-filter=D",
            ).splitlines()
            if line
        }
        remote = _git(root, "remote", "get-url", "origin", check=False)
        repository_identity = canonical_sha256(
            {
                "origin_url_hash": canonical_sha256(remote) if remote else None,
                "git_common_dir_name": Path(
                    _git(root, "rev-parse", "--git-common-dir")
                ).name,
            }
        )
        source_id = f"git_repository:{repository_identity.casefold()}"
        metadata = {
            "repository_identity_sha256": repository_identity,
            "current_branch": branch,
            "head": head,
            "upstream": upstream or None,
            "upstream_sha": origin_sha or None,
            "ahead_behind": divergence or None,
            "commit_count_all": int(_git(root, "rev-list", "--all", "--count")),
            "ref_count": len(refs),
            "tag_count": len(_git(root, "tag", "--list").splitlines()),
            "tracked_change_count": tracked_changes,
            "staged_change_count": staged,
            "untracked_entry_count": untracked,
            "tracked_diff_sha256": tracked_diff_sha256,
            "staged_diff_sha256": staged_diff_sha256,
            "deleted_path_count": len(deleted_paths),
            "all_refs_discoverable": True,
            "renamed_lineage_followable": True,
        }
        state_fingerprint = canonical_sha256(
            {
                "repository_identity": repository_identity,
                "head": head,
                "refs": refs_fingerprint,
                "tracked_change_count": tracked_changes,
                "staged_change_count": staged,
                "tracked_diff_sha256": tracked_diff_sha256,
                "staged_diff_sha256": staged_diff_sha256,
            }
        )
        return SourceRecord(
            source_id=source_id,
            source_type=SourceType.GIT_REPOSITORY,
            path=str(root.absolute()),
            exists=True,
            size_bytes=None,
            sha256=state_fingerprint,
            mtime_utc=datetime.now(timezone.utc).isoformat(),
            format="git/repository-state",
            privacy_class=PrivacyClass.PROJECT_GIT,
            discovery_method="git_cli",
            metadata=metadata,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return missing_record(
            root,
            source_type=SourceType.GIT_REPOSITORY,
            privacy_class=PrivacyClass.PROJECT_GIT,
            discovery_method="git_cli",
            error=f"{type(exc).__name__}: {exc}",
        )


def _decision_count(path: Path) -> int:
    if path.name != "orion-master-decision-register-2026-09-01.md":
        return 0
    pattern = re.compile(r"^\| D\d+ \|", re.MULTILINE)
    return len(pattern.findall(path.read_text(encoding="utf-8")))


def discover_project_documents(config: SourceConfig) -> list[SourceRecord]:
    docs_root = config.repository_root / "docs"
    required = (
        "orion-master-architecture-checkpoint-2026-09-01.md",
        "orion-master-decision-register-2026-09-01.md",
        "orion-development-history-2026-09-02.md",
        "ORION_PROJECT_MEMORY.md",
    )
    candidates = [docs_root / name for name in required]
    if docs_root.is_dir():
        candidates.extend(sorted(docs_root.glob("adr-*.md")))
    records: list[SourceRecord] = []
    for path in dict.fromkeys(candidates):
        if not path.is_file():
            records.append(
                missing_record(
                    path,
                    source_type=SourceType.PROJECT_DOCUMENT,
                    privacy_class=PrivacyClass.PROJECT_GIT,
                    discovery_method="project_document_registry",
                )
            )
            continue
        metadata: dict[str, Any] = {"document_name": path.name}
        count = _decision_count(path)
        if count:
            metadata["decision_record_count"] = count
        records.append(
            file_record(
                path,
                source_type=SourceType.PROJECT_DOCUMENT,
                privacy_class=PrivacyClass.PROJECT_GIT,
                discovery_method="project_document_registry",
                format_name="markdown",
                metadata=metadata,
            )
        )
    return records


def discover_all(config: SourceConfig) -> tuple[SourceRecord, ...]:
    records = [
        *discover_chatgpt_archives(config),
        *discover_codex_history(config),
        discover_git(config),
        *discover_evidence(config),
        *discover_releases(config),
        *discover_runtime_artifacts(config),
        *discover_project_documents(config),
    ]
    return tuple(
        sorted(
            records,
            key=lambda record: (
                record.source_type.value,
                record.path.casefold(),
                record.source_id,
            ),
        )
    )
