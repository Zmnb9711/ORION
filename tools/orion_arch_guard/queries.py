from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from tools.orion_arch_guard.schema import connect_index, migrate


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in ("metadata_json", "source_pointer_json"):
        if key in result and result[key]:
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
    return result


def _rows(rows: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict_value for row in rows if (dict_value := _row(row)) is not None]


class HistoryIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = connect_index(path)
        migrate(self.connection)

    def close(self) -> None:
        self.connection.close()

    def status(self) -> dict[str, Any]:
        counts = {
            table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "source_snapshots",
                "sources",
                "source_locations",
                "source_items",
                "item_sources",
            )
        }
        by_type = dict(
            self.connection.execute(
                "SELECT item_type, COUNT(*) FROM source_items GROUP BY item_type ORDER BY item_type"
            )
        )
        unavailable = self.connection.execute(
            "SELECT COUNT(*) FROM sources WHERE availability != 'AVAILABLE'"
        ).fetchone()[0]
        return {
            "database": str(self.path.absolute()),
            "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "counts": counts,
            "items_by_type": by_type,
            "unavailable_or_failed_sources": unavailable,
            "fts5": "DEFERRED",
            "authoritative": False,
        }

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        return _row(
            self.connection.execute(
                "SELECT * FROM source_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        )

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return _row(
            self.connection.execute(
                "SELECT * FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
        )

    def find_native(
        self, native_id: str, *, item_type: str | None = None
    ) -> list[dict[str, Any]]:
        if item_type:
            rows = self.connection.execute(
                "SELECT * FROM source_items WHERE native_id = ? AND item_type = ? ORDER BY timestamp_utc, ordinal",
                (native_id, item_type),
            )
        else:
            rows = self.connection.execute(
                "SELECT * FROM source_items WHERE native_id = ? ORDER BY timestamp_utc, ordinal",
                (native_id,),
            )
        return _rows(rows)

    def children(self, item_id: str) -> list[dict[str, Any]]:
        item = self.get_item(item_id)
        if item is None:
            return []
        rows = self.connection.execute(
            """
            SELECT * FROM source_items
            WHERE (parent_item_id = ?)
               OR (source_id = ? AND parent_native_id = ?)
            ORDER BY ordinal, timestamp_utc
            """,
            (item_id, item["source_id"], item["native_id"]),
        )
        return _rows(rows)

    def parent(self, item_id: str) -> dict[str, Any] | None:
        item = self.get_item(item_id)
        if item is None:
            return None
        if item.get("parent_item_id"):
            parent = self.get_item(str(item["parent_item_id"]))
            if parent is not None:
                return parent
        parent_native = item.get("parent_native_id")
        if not parent_native:
            return None
        return _row(
            self.connection.execute(
                "SELECT * FROM source_items WHERE source_id = ? AND native_id = ? ORDER BY ordinal LIMIT 1",
                (item["source_id"], parent_native),
            ).fetchone()
        )

    def neighbors(self, item_id: str) -> dict[str, Any]:
        item = self.get_item(item_id)
        if item is None:
            return {"item": None, "previous": None, "next": None}
        thread_key = item.get("thread_key")
        if not thread_key:
            return {"item": item, "previous": None, "next": None}
        previous = _row(
            self.connection.execute(
                """
                SELECT * FROM source_items
                WHERE thread_key = ? AND ordinal < ?
                ORDER BY ordinal DESC LIMIT 1
                """,
                (thread_key, item["ordinal"]),
            ).fetchone()
        )
        following = _row(
            self.connection.execute(
                """
                SELECT * FROM source_items
                WHERE thread_key = ? AND ordinal > ?
                ORDER BY ordinal LIMIT 1
                """,
                (thread_key, item["ordinal"]),
            ).fetchone()
        )
        return {"item": item, "previous": previous, "next": following}

    def thread_range(
        self, item_id: str, *, before: int = 2, after: int = 2
    ) -> list[dict[str, Any]]:
        item = self.get_item(item_id)
        if item is None or not item.get("thread_key"):
            return []
        rows = self.connection.execute(
            """
            SELECT * FROM source_items
            WHERE thread_key = ? AND ordinal BETWEEN ? AND ?
            ORDER BY ordinal
            """,
            (
                item["thread_key"],
                int(item["ordinal"]) - max(0, before),
                int(item["ordinal"]) + max(0, after),
            ),
        )
        return _rows(rows)

    def git_path_history(self, path: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM source_items
            WHERE item_type = 'git_path_change'
              AND (json_extract(metadata_json, '$.path') = ?
                   OR json_extract(metadata_json, '$.old_path') = ?)
            ORDER BY timestamp_utc, ordinal
            """,
            (path, path),
        )
        return _rows(rows)

    def timed_lookup(self, item_id: str) -> tuple[dict[str, Any] | None, float]:
        started = time.perf_counter()
        result = self.get_item(item_id)
        return result, (time.perf_counter() - started) * 1000
