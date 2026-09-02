from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.orion_arch_guard.models import PrivacyClass, SourceRecord, SourceType

_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest, _size = sha256_file_and_size(path)
    return digest


def sha256_file_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest().upper(), size


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def stable_content_source_id(source_type: SourceType, sha256: str) -> str:
    return f"{source_type.value}:{sha256.casefold()}"


def stable_locator_source_id(
    source_type: SourceType, logical_name: str, discovery_method: str
) -> str:
    digest = canonical_sha256(
        {
            "source_type": source_type.value,
            "logical_name": logical_name.casefold(),
            "discovery_method": discovery_method,
        }
    )
    return f"{source_type.value}:locator:{digest.casefold()}"


def file_record(
    path: Path,
    *,
    source_type: SourceType,
    privacy_class: PrivacyClass,
    discovery_method: str,
    format_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SourceRecord:
    try:
        digest, hashed_size = sha256_file_and_size(path)
        return SourceRecord(
            source_id=stable_content_source_id(source_type, digest),
            source_type=source_type,
            path=str(path.absolute()),
            exists=True,
            size_bytes=hashed_size,
            sha256=digest,
            mtime_utc=mtime_utc(path),
            format=format_name or path.suffix.removeprefix(".").casefold() or "file",
            privacy_class=privacy_class,
            discovery_method=discovery_method,
            metadata=dict(metadata or {}),
        )
    except OSError as exc:
        return missing_record(
            path,
            source_type=source_type,
            privacy_class=privacy_class,
            discovery_method=discovery_method,
            error=f"{type(exc).__name__}: {exc}",
        )


def missing_record(
    path: Path,
    *,
    source_type: SourceType,
    privacy_class: PrivacyClass,
    discovery_method: str,
    error: str = "source path is unavailable",
) -> SourceRecord:
    return SourceRecord(
        source_id=stable_locator_source_id(
            source_type, path.name or source_type.value, discovery_method
        ),
        source_type=source_type,
        path=str(path.absolute()),
        exists=False,
        size_bytes=None,
        sha256=None,
        mtime_utc=None,
        format="unavailable",
        privacy_class=privacy_class,
        discovery_method=discovery_method,
        metadata={},
        error=error,
    )


def bounded_directory_record(
    path: Path,
    *,
    source_type: SourceType,
    privacy_class: PrivacyClass,
    discovery_method: str,
    entries: Iterable[dict[str, Any]],
    metadata: dict[str, Any],
) -> SourceRecord:
    bounded_entries = sorted(entries, key=lambda item: str(item.get("path", "")))
    digest = canonical_sha256(bounded_entries)
    return SourceRecord(
        source_id=stable_content_source_id(source_type, digest),
        source_type=source_type,
        path=str(path.absolute()),
        exists=True,
        size_bytes=sum(
            int(item.get("size_bytes", 0) or 0) for item in bounded_entries
        ),
        sha256=digest,
        mtime_utc=mtime_utc(path),
        format="directory/bounded-manifest",
        privacy_class=privacy_class,
        discovery_method=discovery_method,
        metadata=metadata,
    )
