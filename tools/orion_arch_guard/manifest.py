from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from tools.orion_arch_guard import AG0_VERSION
from tools.orion_arch_guard.config import SourceConfig
from tools.orion_arch_guard.fingerprints import sha256_file
from tools.orion_arch_guard.models import (
    ChangeStatus,
    Manifest,
    SourceChange,
    SourceRecord,
)

MANIFEST_SCHEMA_VERSION = 1


def build_manifest(
    config: SourceConfig,
    sources: Iterable[SourceRecord],
    *,
    previous_manifest_sha256: str | None = None,
) -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        tool_version=AG0_VERSION,
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        repository_root=str(config.repository_root),
        discovery_config=config.to_dict(),
        previous_manifest_sha256=previous_manifest_sha256,
        sources=tuple(sources),
    )


def read_manifest(path: Path) -> Manifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Manifest.from_dict(payload)


def write_manifest(path: Path, manifest: Manifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        manifest.to_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.write("\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def existing_manifest_sha256(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def compare_sources(
    previous: Iterable[SourceRecord], current: Iterable[SourceRecord]
) -> tuple[SourceChange, ...]:
    old = list(previous)
    new = list(current)
    unmatched_old = set(range(len(old)))
    unmatched_new = set(range(len(new)))
    changes: list[SourceChange] = []

    def append_change(
        status: ChangeStatus,
        old_record: SourceRecord | None,
        new_record: SourceRecord | None,
    ) -> None:
        record = new_record or old_record
        if record is None:
            raise AssertionError("source comparison requires a record")
        changes.append(
            SourceChange(
                status=status,
                source_type=record.source_type,
                source_id=record.source_id,
                old_path=old_record.path if old_record else None,
                new_path=new_record.path if new_record else None,
                old_sha256=old_record.sha256 if old_record else None,
                new_sha256=new_record.sha256 if new_record else None,
            )
        )

    for old_index in list(unmatched_old):
        old_record = old[old_index]
        same_path_index = next(
            (
                index
                for index in unmatched_new
                if new[index].path_key == old_record.path_key
            ),
            None,
        )
        if same_path_index is None:
            continue
        new_record = new[same_path_index]
        unmatched_old.remove(old_index)
        unmatched_new.remove(same_path_index)
        if not old_record.exists and new_record.exists:
            status = ChangeStatus.NEW
        elif old_record.exists and not new_record.exists:
            status = ChangeStatus.MISSING
        elif (
            old_record.exists == new_record.exists
            and old_record.sha256 == new_record.sha256
            and old_record.error == new_record.error
        ):
            status = ChangeStatus.UNCHANGED
        else:
            status = ChangeStatus.CHANGED
        append_change(status, old_record, new_record)

    for old_index in list(unmatched_old):
        old_record = old[old_index]
        relocated_index = next(
            (
                index
                for index in unmatched_new
                if new[index].source_type == old_record.source_type
                and new[index].source_id == old_record.source_id
                and new[index].exists
                and old_record.exists
            ),
            None,
        )
        if relocated_index is None:
            continue
        new_record = new[relocated_index]
        unmatched_old.remove(old_index)
        unmatched_new.remove(relocated_index)
        append_change(ChangeStatus.RELOCATED, old_record, new_record)

    for old_index in sorted(unmatched_old):
        append_change(ChangeStatus.MISSING, old[old_index], None)
    for new_index in sorted(unmatched_new):
        append_change(ChangeStatus.NEW, None, new[new_index])

    return tuple(
        sorted(
            changes,
            key=lambda item: (
                item.status.value,
                item.source_type.value,
                (item.new_path or item.old_path or "").casefold(),
            ),
        )
    )


def change_counts(changes: Iterable[SourceChange]) -> dict[str, int]:
    counts = Counter(change.status.value for change in changes)
    return {status.value: counts[status.value] for status in ChangeStatus}
