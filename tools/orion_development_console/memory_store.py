from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from tools.orion_development_console.memory_models import DevelopmentCheckpoint, PromptRecord


RecordT = TypeVar("RecordT", bound=BaseModel)


class ImmutableRecordStore(Generic[RecordT]):
    """Private create-once JSON records plus a rebuildable derived index."""

    def __init__(self, root: Path, model: type[RecordT], id_field: str) -> None:
        self.root = root
        self.model = model
        self.id_field = id_field
        self.index_path = root / "index.json"

    def _record_path(self, record_id: str) -> Path:
        if not record_id or Path(record_id).name != record_id:
            raise ValueError("record ID must be a single safe path component")
        return self.root / f"{record_id}.json"

    def save_create_once(self, record: RecordT) -> Path:
        validate = getattr(record, "validate_fingerprint", None)
        if callable(validate):
            validate()
        self.root.mkdir(parents=True, exist_ok=True)
        record_id = str(getattr(record, self.id_field))
        target = self._record_path(record_id)
        payload = record.model_dump_json(indent=2) + "\n"
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{record_id}.", suffix=".tmp", dir=self.root
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # A same-directory hard link publishes the complete file atomically and
            # fails when the immutable final name already exists.
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        self.rebuild_index()
        return target

    def load(self, record_id: str) -> RecordT:
        path = self._record_path(record_id)
        try:
            record = self.model.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError) as error:
            raise ValueError(f"invalid immutable record {record_id}: {error}") from error
        validate = getattr(record, "validate_fingerprint", None)
        if callable(validate):
            validate()
        return record

    def list_records(self, *, newest_first: bool = False) -> list[RecordT]:
        records: list[RecordT] = []
        if not self.root.is_dir():
            return records
        for path in self.root.glob("*.json"):
            if path == self.index_path:
                continue
            records.append(self.load(path.stem))
        records.sort(
            key=lambda item: (str(getattr(item, "created_at", "")), str(getattr(item, self.id_field))),
            reverse=newest_first,
        )
        return records

    def latest(self) -> RecordT | None:
        records = self.list_records(newest_first=True)
        return records[0] if records else None

    def rebuild_index(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        entries = []
        for record in self.list_records():
            entries.append(
                {
                    "id": str(getattr(record, self.id_field)),
                    "created_at": str(getattr(record, "created_at", "")),
                    "content_fingerprint": str(getattr(record, "content_fingerprint", "")),
                }
            )
        payload = json.dumps(
            {"schema_version": 1, "records": entries}, ensure_ascii=False, indent=2
        ) + "\n"
        handle, temporary_name = tempfile.mkstemp(
            prefix=".index.", suffix=".tmp", dir=self.root
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.index_path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return self.index_path


class CheckpointStore(ImmutableRecordStore[DevelopmentCheckpoint]):
    def __init__(self, console_root: Path) -> None:
        super().__init__(console_root / "checkpoints", DevelopmentCheckpoint, "checkpoint_id")


class PromptStore(ImmutableRecordStore[PromptRecord]):
    def __init__(self, console_root: Path) -> None:
        super().__init__(console_root / "prompts", PromptRecord, "prompt_id")
