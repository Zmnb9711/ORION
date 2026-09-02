from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from tools.orion_arch_guard import AG1_VERSION
from tools.orion_arch_guard.fingerprints import (
    canonical_sha256,
    sha256_bytes,
    sha256_file,
)
from tools.orion_arch_guard.models import Manifest, PrivacyClass, SourceRecord, SourceType
from tools.orion_arch_guard.privacy import bounded_preview
from tools.orion_arch_guard.schema import PARSER_VERSION, connect_index, migrate

_DECISION_ROW = re.compile(r"^\|\s*(D\d{2})\s*\|", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SHA = re.compile(r"\b[0-9a-fA-F]{40}\b")
_SAFE_SCALAR = re.compile(r"^[\w .:/+@-]{1,160}$", re.UNICODE)
_MUTABLE_ROOT_TYPES = {
    SourceType.CHATGPT_ARCHIVE_ROOT,
    SourceType.CODEX_HISTORY_ROOT,
    SourceType.EVIDENCE_ROOT,
    SourceType.RELEASE_ROOT,
    SourceType.RUNTIME_ROOT,
}
_EVIDENCE_KEYS = {
    "provider",
    "provider_path",
    "radio_stt_provider",
    "test_name",
    "test_label",
    "capability",
    "human_review",
    "human_review_result",
    "acoustic_review",
    "session_id",
    "test_session_id",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _item_id(namespace: str, *parts: object) -> str:
    readable = ":".join(str(part).strip().casefold() for part in parts if str(part))
    return f"{namespace}:{readable}"


@dataclass(frozen=True, slots=True)
class IndexItem:
    item_id: str
    source_id: str
    native_id: str
    parent_native_id: str | None
    parent_item_id: str | None
    thread_key: str | None
    item_type: str
    timestamp_utc: str | None
    author_or_role: str | None
    ordinal: int
    content_sha256: str
    bounded_preview: str | None
    metadata: dict[str, Any]
    privacy_class: str
    source_pointer: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IndexResult:
    database_path: str
    duration_seconds: float
    snapshot_id: str
    sources_seen: int
    sources_ingested: int
    sources_reused: int
    sources_failed: int
    items_upserted: int
    counts: dict[str, int]


def _source_pointer(source: SourceRecord, **location: Any) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "source_type": source.source_type.value,
        "path": source.path,
        "source_sha256": source.sha256,
        **location,
    }


def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, (bool, int, float)) or item is None:
            result[str(key)] = item
        elif isinstance(item, str) and _SAFE_SCALAR.fullmatch(item):
            result[str(key)] = item
        elif isinstance(item, list):
            safe = [entry for entry in item if isinstance(entry, str) and _SAFE_SCALAR.fullmatch(entry)]
            result[str(key)] = safe[:64]
    return result


def _message_text(content: Any) -> str:
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    values: list[str] = []
    for part in parts:
        if isinstance(part, str):
            values.append(part)
        elif isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                values.append(text)
    return "\n".join(values)


def _timestamp(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str) and value:
        return value
    return None


def _chatgpt_items(source: SourceRecord) -> Iterator[IndexItem]:
    with zipfile.ZipFile(source.path) as archive:
        with archive.open("conversations.json") as stream:
            conversations = json.load(stream)
    for conversation_ordinal, conversation in enumerate(conversations):
        conversation_id = str(conversation.get("id") or f"ordinal-{conversation_ordinal}")
        title = str(conversation.get("title") or "Untitled conversation")
        mapping = conversation.get("mapping") or {}
        current_node = conversation.get("current_node")
        principal: list[str] = []
        cursor = current_node
        seen: set[str] = set()
        while cursor and cursor not in seen and cursor in mapping:
            principal.append(str(cursor))
            seen.add(str(cursor))
            cursor = mapping[cursor].get("parent")
        principal.reverse()
        principal_ordinals = {node_id: index for index, node_id in enumerate(principal)}
        conversation_hash = canonical_sha256(
            {
                "id": conversation_id,
                "title": title,
                "create_time": conversation.get("create_time"),
                "update_time": conversation.get("update_time"),
            }
        )
        yield IndexItem(
            item_id=_item_id(
                "chatgpt:conversation", conversation_id, conversation_hash[:16]
            ),
            source_id=source.source_id,
            native_id=conversation_id,
            parent_native_id=None,
            parent_item_id=None,
            thread_key=f"chatgpt:{conversation_id}",
            item_type="chatgpt_conversation",
            timestamp_utc=_timestamp(conversation.get("create_time")),
            author_or_role=None,
            ordinal=conversation_ordinal,
            content_sha256=conversation_hash,
            bounded_preview=bounded_preview(title),
            metadata={
                "title": bounded_preview(title),
                "updated_at_utc": _timestamp(conversation.get("update_time")),
                "node_count": len(mapping),
                "principal_node_count": len(principal),
            },
            privacy_class=source.privacy_class.value,
            source_pointer=_source_pointer(
                source,
                archive_entry="conversations.json",
                conversation_id=conversation_id,
            ),
        )
        alternative_nodes = sorted(
            (str(node_id) for node_id in mapping if str(node_id) not in principal_ordinals),
            key=lambda node_id: (
                mapping[node_id].get("message", {}).get("create_time") or 0,
                node_id,
            ),
        )
        structural_order = principal + alternative_nodes
        for structural_ordinal, node_id in enumerate(structural_order):
            node = mapping[node_id]
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            native_message_id = str(message.get("id") or node_id)
            content = message.get("content") or {}
            content_hash = canonical_sha256(content)
            author = message.get("author") or {}
            role = str(author.get("role")) if author.get("role") else None
            parent_native = str(node.get("parent")) if node.get("parent") else None
            branch = "principal" if node_id in principal_ordinals else "alternative"
            ordinal = principal_ordinals.get(node_id, len(principal) + structural_ordinal)
            yield IndexItem(
                item_id=_item_id(
                    "chatgpt:message",
                    conversation_id,
                    node_id,
                    content_hash[:16],
                ),
                source_id=source.source_id,
                native_id=node_id,
                parent_native_id=parent_native,
                parent_item_id=None,
                thread_key=f"chatgpt:{conversation_id}:{branch}",
                item_type="chatgpt_message",
                timestamp_utc=_timestamp(message.get("create_time")),
                author_or_role=role,
                ordinal=ordinal,
                content_sha256=content_hash,
                bounded_preview=bounded_preview(_message_text(content)),
                metadata={
                    "conversation_id": conversation_id,
                    "message_id": native_message_id,
                    "branch_classification": branch,
                    "principal_ordinal": principal_ordinals.get(node_id),
                    "structural_ordinal": structural_ordinal,
                    "child_count": len(node.get("children") or []),
                },
                privacy_class=source.privacy_class.value,
                source_pointer=_source_pointer(
                    source,
                    archive_entry="conversations.json",
                    conversation_id=conversation_id,
                    node_id=node_id,
                    message_id=native_message_id,
                    ordinal=ordinal,
                    branch=branch,
                ),
            )


def _codex_identity(path: Path) -> str:
    match = re.search(r"([0-9a-f]{8}-[0-9a-f-]{20,})", path.name, re.IGNORECASE)
    return (match.group(1) if match else path.stem).casefold()


def _codex_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _codex_text(item)))
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            part = _codex_text(value.get(key))
            if part:
                return part
    return ""


def _codex_items(source: SourceRecord) -> Iterator[IndexItem]:
    session = _codex_identity(Path(source.path))
    with Path(source.path).open("rb") as stream:
        for ordinal, raw in enumerate(stream):
            stripped = raw.rstrip(b"\r\n")
            if not stripped:
                continue
            content_hash = sha256_bytes(stripped)
            try:
                decoded = json.loads(stripped)
            except (UnicodeDecodeError, json.JSONDecodeError):
                decoded = {}
            event: dict[str, Any] = decoded if isinstance(decoded, dict) else {}
            raw_payload = event.get("payload")
            payload: dict[str, Any] = (
                raw_payload if isinstance(raw_payload, dict) else {}
            )
            native = next(
                (
                    str(value)
                    for value in (
                        event.get("id"),
                        payload.get("id"),
                        payload.get("item_id"),
                        payload.get("call_id"),
                    )
                    if value
                ),
                f"line-{ordinal}-{content_hash[:16].casefold()}",
            )
            event_type = str(event.get("type") or payload.get("type") or "jsonl_event")
            role = payload.get("role")
            content = _codex_text(payload.get("content")) or _codex_text(
                payload.get("text")
            )
            ids = {
                key: str(payload[key])
                for key in ("call_id", "item_id", "parent_id", "conversation_id")
                if payload.get(key)
            }
            sha = next(iter(_SHA.findall(stripped.decode("utf-8", errors="ignore"))), None)
            metadata: dict[str, Any] = {"event_type": event_type, **ids}
            if sha:
                metadata["explicit_git_sha"] = sha.casefold()
            parent_native = str(payload.get("parent_id")) if payload.get("parent_id") else None
            yield IndexItem(
                item_id=_item_id("codex", session, ordinal, native, content_hash[:16]),
                source_id=source.source_id,
                native_id=native,
                parent_native_id=parent_native,
                parent_item_id=None,
                thread_key=f"codex:{session}",
                item_type=f"codex_{event_type}",
                timestamp_utc=_timestamp(event.get("timestamp") or payload.get("timestamp")),
                author_or_role=str(role) if role else None,
                ordinal=ordinal,
                content_sha256=content_hash,
                bounded_preview=bounded_preview(content),
                metadata=metadata,
                privacy_class=source.privacy_class.value,
                source_pointer=_source_pointer(
                    source,
                    jsonl_ordinal=ordinal,
                    native_event_id=native,
                    session_identity=session,
                ),
            )


def _git_output(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


def _git_items(source: SourceRecord) -> Iterator[IndexItem]:
    repository = Path(source.path)
    ref_map: dict[str, list[str]] = {}
    for line in _git_output(repository, "show-ref").splitlines():
        sha, _, ref = line.partition(" ")
        ref_map.setdefault(sha, []).append(ref)
    output = _git_output(
        repository,
        "log",
        "--all",
        "--reverse",
        "--topo-order",
        "-M",
        "--format=%x1e%H%x1f%P%x1f%aI%x1f%an%x1f%ae%x1f%s",
        "--name-status",
    )
    commit_ordinal = 0
    repository_identity = source.metadata.get("repository_identity_sha256")
    for record in output.split("\x1e"):
        record = record.lstrip("\r\n")
        if not record:
            continue
        lines = record.splitlines()
        fields = lines[0].split("\x1f")
        if len(fields) != 6:
            continue
        sha, parents, timestamp, author, email, subject = fields
        commit_id = _item_id("git:commit", sha)
        parent_sha = parents.split()[0] if parents else None
        yield IndexItem(
            item_id=commit_id,
            source_id=source.source_id,
            native_id=sha,
            parent_native_id=parent_sha,
            parent_item_id=_item_id("git:commit", parent_sha) if parent_sha else None,
            thread_key="git:all",
            item_type="git_commit",
            timestamp_utc=timestamp or None,
            author_or_role=author,
            ordinal=commit_ordinal,
            content_sha256=sha.upper(),
            bounded_preview=bounded_preview(subject),
            metadata={
                "parents": parents.split(),
                "author_email": email,
                "refs": sorted(ref_map.get(sha, [])),
            },
            privacy_class=source.privacy_class.value,
            source_pointer=_source_pointer(
                source,
                repository_identity=repository_identity,
                commit_sha=sha,
            ),
        )
        change_ordinal = 0
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            change_type = parts[0]
            paths = parts[1:]
            path = paths[-1]
            native = f"{sha}:{change_ordinal}:{canonical_sha256([change_type, *paths])[:16]}"
            yield IndexItem(
                item_id=_item_id("git:path", native),
                source_id=source.source_id,
                native_id=native,
                parent_native_id=sha,
                parent_item_id=commit_id,
                thread_key=f"git:path:{path.casefold()}",
                item_type="git_path_change",
                timestamp_utc=timestamp or None,
                author_or_role=author,
                ordinal=change_ordinal,
                content_sha256=canonical_sha256([sha, change_type, *paths]),
                bounded_preview=bounded_preview(f"{change_type} {' -> '.join(paths)}"),
                metadata={
                    "commit_sha": sha,
                    "change_type": change_type,
                    "path": path,
                    "old_path": paths[0] if len(paths) > 1 else None,
                    "lineage_hint": "explicit_rename" if change_type.startswith("R") else "history_followable",
                },
                privacy_class=source.privacy_class.value,
                source_pointer=_source_pointer(
                    source,
                    repository_identity=repository_identity,
                    commit_sha=sha,
                    path=path,
                    old_path=paths[0] if len(paths) > 1 else None,
                    change_type=change_type,
                ),
            )
            change_ordinal += 1
        commit_ordinal += 1


def _count_zip_events(archive: zipfile.ZipFile) -> int | None:
    name = next((name for name in archive.namelist() if Path(name).name.casefold() == "events.jsonl"), None)
    if name is None:
        return None
    count = 0
    with archive.open(name) as stream:
        for line in stream:
            if line.strip():
                count += 1
    return count


def _evidence_items(source: SourceRecord) -> Iterator[IndexItem]:
    event_count: int | None = None
    entries: list[str] = []
    explicit: dict[str, str] = {}
    try:
        with zipfile.ZipFile(source.path) as archive:
            entries = [Path(info.filename).name for info in archive.infolist()][:256]
            event_count = _count_zip_events(archive)
            for archive_name in archive.namelist():
                if Path(archive_name).name.casefold() not in {
                    "manifest.txt",
                    "session-summary.txt",
                    "timing-summary.txt",
                }:
                    continue
                with archive.open(archive_name) as stream:
                    text = stream.read(256 * 1024).decode("utf-8", errors="replace")
                for line in text.splitlines():
                    key, separator, raw_value = line.partition("=")
                    if not separator:
                        key, separator, raw_value = line.partition(":")
                    normalized_key = key.strip().casefold()
                    preview = bounded_preview(raw_value, limit=160)
                    if (
                        separator
                        and normalized_key in _EVIDENCE_KEYS
                        and preview
                    ):
                        explicit.setdefault(normalized_key, preview)
    except (OSError, zipfile.BadZipFile):
        pass
    timestamp_match = re.search(r"(20\d{6}-\d{6})", Path(source.path).name)
    timestamp = None
    if timestamp_match:
        try:
            timestamp = datetime.strptime(timestamp_match.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    metadata = {
        **_safe_metadata(source.metadata),
        **explicit,
        "event_count": event_count,
        "entry_names": entries,
        "raw_audio_ingested": False,
    }
    yield IndexItem(
        item_id=_item_id("evidence", source.sha256 or source.source_id),
        source_id=source.source_id,
        native_id=source.sha256 or source.source_id,
        parent_native_id=None,
        parent_item_id=None,
        thread_key="evidence",
        item_type="evidence_archive",
        timestamp_utc=timestamp or source.mtime_utc,
        author_or_role=None,
        ordinal=0,
        content_sha256=source.sha256 or canonical_sha256(source.path),
        bounded_preview=bounded_preview(Path(source.path).name),
        metadata=metadata,
        privacy_class=source.privacy_class.value,
        source_pointer=_source_pointer(source, internal_metadata_entries=source.metadata.get("metadata_entries_checked", [])),
    )


def _document_items(source: SourceRecord) -> Iterator[IndexItem]:
    path = Path(source.path)
    lines = path.read_text(encoding="utf-8").splitlines()
    repository = path.parent.parent
    try:
        git_sha = _git_output(repository, "rev-parse", "HEAD").strip()
    except (OSError, subprocess.SubprocessError):
        git_sha = None
    sections: list[tuple[int, int, str, int]] = []
    headings: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines, start=1):
        match = _HEADING.match(line)
        if match:
            headings.append((index, match.group(2), len(match.group(1))))
    for index, (start, title, level) in enumerate(headings):
        end = headings[index + 1][0] - 1 if index + 1 < len(headings) else len(lines)
        sections.append((start, end, title, level))
    relative = path.relative_to(repository).as_posix() if path.is_relative_to(repository) else path.name
    for ordinal, (start, end, title, level) in enumerate(sections):
        body = "\n".join(lines[start - 1 : end])
        content_hash = canonical_sha256(body)
        yield IndexItem(
            item_id=_item_id("document:section", relative, start, content_hash[:16]),
            source_id=source.source_id,
            native_id=f"section:{start}",
            parent_native_id=None,
            parent_item_id=None,
            thread_key=f"document:{relative}",
            item_type="document_section",
            timestamp_utc=source.mtime_utc,
            author_or_role=None,
            ordinal=ordinal,
            content_sha256=content_hash,
            bounded_preview=bounded_preview(title),
            metadata={"heading": bounded_preview(title), "heading_level": level, "line_start": start, "line_end": end},
            privacy_class=source.privacy_class.value,
            source_pointer=_source_pointer(source, git_sha=git_sha, path=relative, line_start=start, line_end=end, section=title, content_sha256=content_hash),
        )
    decision_ordinal = 0
    for line_number, line in enumerate(lines, start=1):
        match = _DECISION_ROW.match(line)
        if not match:
            continue
        decision_id = match.group(1).upper()
        content_hash = canonical_sha256(line)
        yield IndexItem(
            item_id=_item_id("document:decision", decision_id, content_hash[:16]),
            source_id=source.source_id,
            native_id=decision_id,
            parent_native_id=None,
            parent_item_id=None,
            thread_key="document:decision-register",
            item_type="decision_register_row",
            timestamp_utc=source.mtime_utc,
            author_or_role=None,
            ordinal=decision_ordinal,
            content_sha256=content_hash,
            bounded_preview=bounded_preview(line),
            metadata={"decision_id": decision_id, "line": line_number},
            privacy_class=source.privacy_class.value,
            source_pointer=_source_pointer(source, git_sha=git_sha, path=relative, line_start=line_number, line_end=line_number, decision_id=decision_id, content_sha256=content_hash),
        )
        decision_ordinal += 1


def _generic_items(source: SourceRecord) -> Iterator[IndexItem]:
    if source.source_type in _MUTABLE_ROOT_TYPES:
        return
    metadata = _safe_metadata(source.metadata)
    yield IndexItem(
        item_id=_item_id("source:item", source.source_id),
        source_id=source.source_id,
        native_id=source.source_id,
        parent_native_id=None,
        parent_item_id=None,
        thread_key=f"source:{source.source_type.value}",
        item_type=f"{source.source_type.value}_metadata",
        timestamp_utc=source.mtime_utc,
        author_or_role=None,
        ordinal=0,
        content_sha256=source.sha256 or canonical_sha256(metadata),
        bounded_preview=bounded_preview(Path(source.path).name),
        metadata=metadata,
        privacy_class=source.privacy_class.value,
        source_pointer=_source_pointer(source),
    )
    if source.source_type is not SourceType.RELEASE_TREE:
        return
    release = Path(source.path)
    candidates: dict[str, Path] = {}
    for pattern in ("*.exe", "*.msi", "*.zip", "build-identity.json"):
        for candidate in release.glob(pattern):
            if candidate.is_file():
                candidates[candidate.relative_to(release).as_posix()] = candidate
    for candidate in release.rglob("build-identity.json"):
        if candidate.is_file():
            candidates[candidate.relative_to(release).as_posix()] = candidate
        if len(candidates) >= 512:
            break
    for ordinal, (relative, candidate) in enumerate(sorted(candidates.items())[:512]):
        stat = candidate.stat()
        content_hash = (
            sha256_file(candidate)
            if candidate.name.casefold() == "build-identity.json"
            else canonical_sha256(
                {"path": relative, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            )
        )
        yield IndexItem(
            item_id=_item_id("release:artifact", source.source_id, relative),
            source_id=source.source_id,
            native_id=relative,
            parent_native_id=source.source_id,
            parent_item_id=_item_id("source:item", source.source_id),
            thread_key=f"release:{source.source_id}",
            item_type="release_artifact",
            timestamp_utc=source.mtime_utc,
            author_or_role=None,
            ordinal=ordinal,
            content_sha256=content_hash,
            bounded_preview=bounded_preview(relative),
            metadata={"relative_path": relative, "size_bytes": stat.st_size},
            privacy_class=source.privacy_class.value,
            source_pointer=_source_pointer(
                source,
                release_artifact=relative,
                artifact_content_sha256=(
                    content_hash
                    if candidate.name.casefold() == "build-identity.json"
                    else None
                ),
            ),
        )


def iter_source_items(source: SourceRecord) -> Iterator[IndexItem]:
    if not source.exists:
        return
    if source.source_type is SourceType.CHATGPT_ARCHIVE:
        yield from _chatgpt_items(source)
    elif source.source_type is SourceType.CODEX_ROLLOUT:
        yield from _codex_items(source)
    elif source.source_type is SourceType.GIT_REPOSITORY:
        yield from _git_items(source)
    elif source.source_type is SourceType.EVIDENCE_ZIP:
        yield from _evidence_items(source)
    elif source.source_type is SourceType.PROJECT_DOCUMENT:
        yield from _document_items(source)
    else:
        yield from _generic_items(source)


def _upsert_source(
    connection: sqlite3.Connection,
    source: SourceRecord,
    snapshot_id: str,
) -> tuple[bool, bool]:
    prior = connection.execute(
        "SELECT indexed_sha256, parser_version FROM sources WHERE source_id = ?",
        (source.source_id,),
    ).fetchone()
    reusable = bool(
        prior
        and source.exists
        and prior["indexed_sha256"] == source.sha256
        and prior["parser_version"] == PARSER_VERSION
    )
    parser_refresh = bool(
        prior
        and source.exists
        and prior["indexed_sha256"] == source.sha256
        and prior["parser_version"] != PARSER_VERSION
    )
    connection.execute(
        """
        INSERT INTO sources(
            source_id, source_type, path_reference, exists_flag, size_bytes, sha256,
            mtime_utc, format, privacy_class, discovery_method, metadata_json,
            manifest_snapshot, availability, indexed_sha256, indexed_at_utc,
            parser_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            path_reference=excluded.path_reference,
            exists_flag=excluded.exists_flag,
            size_bytes=excluded.size_bytes,
            sha256=excluded.sha256,
            mtime_utc=excluded.mtime_utc,
            format=excluded.format,
            privacy_class=excluded.privacy_class,
            discovery_method=excluded.discovery_method,
            metadata_json=excluded.metadata_json,
            manifest_snapshot=excluded.manifest_snapshot,
            availability=excluded.availability
        """,
        (
            source.source_id,
            source.source_type.value,
            source.path,
            int(source.exists),
            source.size_bytes,
            source.sha256,
            source.mtime_utc,
            source.format,
            source.privacy_class.value,
            source.discovery_method,
            _json(_safe_metadata(source.metadata)),
            snapshot_id,
            "AVAILABLE" if source.exists else "UNAVAILABLE",
            prior["indexed_sha256"] if prior else None,
            None,
            prior["parser_version"] if prior else None,
        ),
    )
    connection.execute(
        """
        INSERT INTO source_locations(source_id, path_reference, first_snapshot, last_snapshot, available)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id, path_reference) DO UPDATE SET
            last_snapshot=excluded.last_snapshot, available=excluded.available
        """,
        (source.source_id, source.path, snapshot_id, snapshot_id, int(source.exists)),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO snapshot_sources(
            snapshot_id, source_id, path_reference, sha256, exists_flag, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, source.source_id, source.path, source.sha256, int(source.exists), _json(_safe_metadata(source.metadata))),
    )
    if not source.exists:
        connection.execute(
            "UPDATE source_locations SET available = 0, last_snapshot = ? WHERE path_reference = ?",
            (snapshot_id, source.path),
        )
        connection.execute(
            """
            UPDATE sources SET availability = 'UNAVAILABLE', exists_flag = 0
            WHERE source_id IN (
                SELECT source_id FROM source_locations WHERE path_reference = ?
            )
            """,
            (source.path,),
        )
    return reusable, parser_refresh


def _remove_parser_stale_items(
    connection: sqlite3.Connection, source_id: str
) -> None:
    connection.execute("DELETE FROM item_sources WHERE source_id = ?", (source_id,))
    connection.execute(
        """
        DELETE FROM source_items
        WHERE source_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM item_sources WHERE item_sources.item_id = source_items.item_id
          )
        """,
        (source_id,),
    )


def _upsert_item(connection: sqlite3.Connection, item: IndexItem) -> None:
    values = (
        item.item_id,
        item.source_id,
        item.native_id,
        item.parent_native_id,
        item.parent_item_id,
        item.thread_key,
        item.item_type,
        item.timestamp_utc,
        item.author_or_role,
        item.ordinal,
        item.content_sha256,
        item.bounded_preview,
        _json(item.metadata),
        item.privacy_class,
        _json(item.source_pointer),
    )
    connection.execute(
        """
        INSERT INTO source_items(
            item_id, source_id, native_id, parent_native_id, parent_item_id,
            thread_key, item_type, timestamp_utc, author_or_role, ordinal,
            content_sha256, bounded_preview, metadata_json, privacy_class,
            source_pointer_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
            source_id=excluded.source_id,
            parent_native_id=excluded.parent_native_id,
            parent_item_id=excluded.parent_item_id,
            thread_key=excluded.thread_key,
            timestamp_utc=excluded.timestamp_utc,
            author_or_role=excluded.author_or_role,
            ordinal=excluded.ordinal,
            content_sha256=excluded.content_sha256,
            bounded_preview=excluded.bounded_preview,
            metadata_json=excluded.metadata_json,
            privacy_class=excluded.privacy_class,
            source_pointer_json=excluded.source_pointer_json
        """,
        values,
    )
    connection.execute(
        "INSERT OR REPLACE INTO item_sources(item_id, source_id, source_pointer_json) VALUES (?, ?, ?)",
        (item.item_id, item.source_id, _json(item.source_pointer)),
    )


def index_manifest(
    manifest: Manifest,
    database_path: Path,
    *,
    manifest_sha256: str,
) -> IndexResult:
    started = time.perf_counter()
    effective_fingerprint = canonical_sha256(
        [
            {
                "source_id": source.source_id,
                "path": source.path,
                "sha256": source.sha256,
                "exists": source.exists,
            }
            for source in manifest.sources
        ]
    )
    snapshot_id = f"snapshot:{effective_fingerprint.casefold()}"
    connection = connect_index(database_path)
    migrate(connection)
    connection.execute(
        """
        INSERT OR IGNORE INTO source_snapshots(
            snapshot_id, manifest_sha256, manifest_generated_at_utc,
            indexed_at_utc, source_count, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            manifest_sha256,
            manifest.generated_at_utc,
            _utc_now(),
            len(manifest.sources),
            _json({"tool_version": AG1_VERSION, "repository_root": manifest.repository_root}),
        ),
    )
    ingested = reused = failed = item_count = 0
    counts: Counter[str] = Counter()
    seen_source_ids: set[str] = set()
    for source_number, source in enumerate(manifest.sources):
        reusable, parser_refresh = _upsert_source(connection, source, snapshot_id)
        if source.source_id in seen_source_ids:
            reused += 1
            continue
        seen_source_ids.add(source.source_id)
        if reusable or not source.exists:
            reused += 1
            continue
        savepoint = f"source_{source_number}"
        connection.execute(f"SAVEPOINT {savepoint}")
        try:
            if parser_refresh:
                _remove_parser_stale_items(connection, source.source_id)
            for item in iter_source_items(source):
                _upsert_item(connection, item)
                item_count += 1
                counts[item.item_type] += 1
            connection.execute(
                """
                UPDATE sources SET indexed_sha256 = ?, indexed_at_utc = ?, parser_version = ?
                WHERE source_id = ?
                """,
                (source.sha256, _utc_now(), PARSER_VERSION, source.source_id),
            )
            ingested += 1
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            failed += 1
            connection.execute(
                "UPDATE sources SET availability = ?, metadata_json = ? WHERE source_id = ?",
                ("INDEX_FAILED", _json({"index_error": f"{type(exc).__name__}: {exc}"}), source.source_id),
            )
    connection.commit()
    connection.close()
    return IndexResult(
        database_path=str(database_path.absolute()),
        duration_seconds=time.perf_counter() - started,
        snapshot_id=snapshot_id,
        sources_seen=len(manifest.sources),
        sources_ingested=ingested,
        sources_reused=reused,
        sources_failed=failed,
        items_upserted=item_count,
        counts=dict(counts),
    )
