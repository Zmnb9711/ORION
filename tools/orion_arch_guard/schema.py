from __future__ import annotations

import sqlite3
from pathlib import Path

INDEX_SCHEMA_VERSION = "1"
PARSER_VERSION = "3"
GUARD_RULESET_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    manifest_sha256 TEXT NOT NULL,
    manifest_generated_at_utc TEXT NOT NULL,
    indexed_at_utc TEXT NOT NULL,
    source_count INTEGER NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    path_reference TEXT NOT NULL,
    exists_flag INTEGER NOT NULL,
    size_bytes INTEGER,
    sha256 TEXT,
    mtime_utc TEXT,
    format TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    discovery_method TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    manifest_snapshot TEXT NOT NULL,
    availability TEXT NOT NULL,
    indexed_sha256 TEXT,
    indexed_at_utc TEXT,
    parser_version TEXT,
    FOREIGN KEY (manifest_snapshot) REFERENCES source_snapshots(snapshot_id)
);

CREATE TABLE IF NOT EXISTS source_locations (
    source_id TEXT NOT NULL,
    path_reference TEXT NOT NULL,
    first_snapshot TEXT NOT NULL,
    last_snapshot TEXT NOT NULL,
    available INTEGER NOT NULL,
    PRIMARY KEY (source_id, path_reference),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS snapshot_sources (
    snapshot_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    path_reference TEXT NOT NULL,
    sha256 TEXT,
    exists_flag INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, source_id, path_reference),
    FOREIGN KEY (snapshot_id) REFERENCES source_snapshots(snapshot_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS source_items (
    item_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    native_id TEXT NOT NULL,
    parent_native_id TEXT,
    parent_item_id TEXT,
    thread_key TEXT,
    item_type TEXT NOT NULL,
    timestamp_utc TEXT,
    author_or_role TEXT,
    ordinal INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    bounded_preview TEXT,
    metadata_json TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    source_pointer_json TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS item_sources (
    item_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_pointer_json TEXT NOT NULL,
    PRIMARY KEY (item_id, source_id),
    FOREIGN KEY (item_id) REFERENCES source_items(item_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);
CREATE INDEX IF NOT EXISTS idx_sources_sha ON sources(sha256);
CREATE INDEX IF NOT EXISTS idx_source_items_source_native
    ON source_items(source_id, native_id);
CREATE INDEX IF NOT EXISTS idx_source_items_native ON source_items(native_id);
CREATE INDEX IF NOT EXISTS idx_source_items_time ON source_items(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_source_items_hash ON source_items(content_sha256);
CREATE INDEX IF NOT EXISTS idx_source_items_thread_ordinal
    ON source_items(thread_key, ordinal);
CREATE INDEX IF NOT EXISTS idx_source_items_parent
    ON source_items(source_id, parent_native_id);
CREATE INDEX IF NOT EXISTS idx_source_items_type ON source_items(item_type);

CREATE TABLE IF NOT EXISTS capabilities (capability_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS decisions (decision_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS implementations (implementation_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS mechanisms (mechanism_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS evidence (evidence_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS performance_metrics (metric_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS relationships (relationship_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS guard_runs (run_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS guard_conflicts (conflict_id TEXT PRIMARY KEY);
"""


def connect_index(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    connection.executescript(_SCHEMA)
    expected = {
        "INDEX_SCHEMA_VERSION": INDEX_SCHEMA_VERSION,
        "PARSER_VERSION": PARSER_VERSION,
        "GUARD_RULESET_VERSION": GUARD_RULESET_VERSION,
    }
    existing = dict(connection.execute("SELECT key, value FROM schema_metadata"))
    schema_value = existing.get("INDEX_SCHEMA_VERSION")
    if schema_value is not None and schema_value != INDEX_SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported index schema {schema_value}; expected {INDEX_SCHEMA_VERSION}"
        )
    connection.executemany(
        "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
        expected.items(),
    )
    connection.commit()
