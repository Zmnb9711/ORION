from __future__ import annotations

import sqlite3
from pathlib import Path

INDEX_SCHEMA_VERSION = "3"
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

CREATE TABLE IF NOT EXISTS capability_aliases (
    alias_key TEXT PRIMARY KEY,
    capability_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    FOREIGN KEY (capability_id) REFERENCES capabilities(capability_id)
);

CREATE TABLE IF NOT EXISTS graph_provenance (
    provenance_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    node_id TEXT NOT NULL,
    source_item_id TEXT,
    source_pointer_json TEXT NOT NULL,
    provenance_kind TEXT NOT NULL,
    confidence TEXT NOT NULL,
    context_item_ids_json TEXT NOT NULL,
    FOREIGN KEY (source_item_id) REFERENCES source_items(item_id)
);

CREATE TABLE IF NOT EXISTS ownership_assignments (
    assignment_id TEXT PRIMARY KEY,
    ownership_role TEXT NOT NULL,
    owner_node_type TEXT NOT NULL,
    owner_node_id TEXT NOT NULL,
    capability_id TEXT,
    historical_status TEXT NOT NULL,
    confidence TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    FOREIGN KEY (capability_id) REFERENCES capabilities(capability_id)
);

CREATE TABLE IF NOT EXISTS graph_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_GRAPH_COLUMNS: dict[str, tuple[str, ...]] = {
    "capabilities": (
        "family TEXT NOT NULL DEFAULT ''",
        "name TEXT NOT NULL DEFAULT ''",
        "description TEXT NOT NULL DEFAULT ''",
        "aliases_json TEXT NOT NULL DEFAULT '[]'",
        "historical_terms_json TEXT NOT NULL DEFAULT '[]'",
        "code_symbols_json TEXT NOT NULL DEFAULT '[]'",
        "providers_json TEXT NOT NULL DEFAULT '[]'",
        "related_domains_json TEXT NOT NULL DEFAULT '[]'",
        "metadata_json TEXT NOT NULL DEFAULT '{}'",
    ),
    "decisions": (
        "decision_date TEXT",
        "area TEXT NOT NULL DEFAULT ''",
        "decision_text TEXT NOT NULL DEFAULT ''",
        "proposed_by TEXT NOT NULL DEFAULT ''",
        "user_approval TEXT NOT NULL DEFAULT ''",
        "historical_implementation TEXT NOT NULL DEFAULT ''",
        "current_implementation TEXT NOT NULL DEFAULT ''",
        "decision_status TEXT NOT NULL DEFAULT ''",
        "superseded_by_json TEXT NOT NULL DEFAULT '[]'",
        "evidence_summary TEXT NOT NULL DEFAULT ''",
        "confidence TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "source_item_id TEXT",
        "metadata_json TEXT NOT NULL DEFAULT '{}'",
    ),
    "implementations": (
        "name TEXT NOT NULL DEFAULT ''",
        "provider TEXT",
        "session_model TEXT",
        "runtime_status TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "historical_status TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "introduced_at TEXT",
        "commit_range_json TEXT NOT NULL DEFAULT '[]'",
        "files_components_json TEXT NOT NULL DEFAULT '[]'",
        "strengths_json TEXT NOT NULL DEFAULT '[]'",
        "defects_json TEXT NOT NULL DEFAULT '[]'",
        "abandonment_reason TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "metadata_json TEXT NOT NULL DEFAULT '{}'",
    ),
    "mechanisms": (
        "name TEXT NOT NULL DEFAULT ''",
        "description TEXT NOT NULL DEFAULT ''",
        "invariant_text TEXT NOT NULL DEFAULT ''",
        "current_presence INTEGER NOT NULL DEFAULT 0",
        "historical_status TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "field_probe_status TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "strengths_json TEXT NOT NULL DEFAULT '[]'",
        "defects_json TEXT NOT NULL DEFAULT '[]'",
        "metadata_json TEXT NOT NULL DEFAULT '{}'",
    ),
    "evidence": (
        "name TEXT NOT NULL DEFAULT ''",
        "evidence_type TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "evidence_status TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "source_item_id TEXT",
        "metadata_json TEXT NOT NULL DEFAULT '{}'",
    ),
    "relationships": (
        "source_node_type TEXT NOT NULL DEFAULT ''",
        "source_node_id TEXT NOT NULL DEFAULT ''",
        "relationship_type TEXT NOT NULL DEFAULT ''",
        "target_node_type TEXT NOT NULL DEFAULT ''",
        "target_node_id TEXT NOT NULL DEFAULT ''",
        "confidence TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "provenance_json TEXT NOT NULL DEFAULT '{}'",
        "metadata_json TEXT NOT NULL DEFAULT '{}'",
    ),
    "performance_metrics": (
        "name TEXT NOT NULL DEFAULT ''",
        "capability_id TEXT",
        "implementation_id TEXT",
        "metric_name TEXT NOT NULL DEFAULT ''",
        "metric_value REAL",
        "unit TEXT NOT NULL DEFAULT ''",
        "boundary TEXT NOT NULL DEFAULT ''",
        "statistic TEXT NOT NULL DEFAULT ''",
        "sample_count INTEGER",
        "comparability TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "evidence_id TEXT",
        "source_item_id TEXT",
        "metadata_json TEXT NOT NULL DEFAULT '{}'",
    ),
    "guard_runs": (
        "created_at_utc TEXT NOT NULL DEFAULT ''",
        "mode_requested TEXT NOT NULL DEFAULT ''",
        "mode_effective TEXT NOT NULL DEFAULT ''",
        "task_hash TEXT NOT NULL DEFAULT ''",
        "head_sha TEXT NOT NULL DEFAULT ''",
        "ruleset_version TEXT NOT NULL DEFAULT ''",
        "index_signature TEXT NOT NULL DEFAULT ''",
        "logical_signature TEXT NOT NULL DEFAULT ''",
        "gate TEXT NOT NULL DEFAULT ''",
        "input_json TEXT NOT NULL DEFAULT '{}'",
        "output_json TEXT NOT NULL DEFAULT '{}'",
        "human_report_path TEXT",
        "json_report_path TEXT",
    ),
    "guard_conflicts": (
        "run_id TEXT",
        "conflict_type TEXT NOT NULL DEFAULT ''",
        "severity TEXT NOT NULL DEFAULT ''",
        "description TEXT NOT NULL DEFAULT ''",
        "decision_ids_json TEXT NOT NULL DEFAULT '[]'",
        "implementation_ids_json TEXT NOT NULL DEFAULT '[]'",
        "provenance_json TEXT NOT NULL DEFAULT '{}'",
    ),
}


def _ensure_columns(connection: sqlite3.Connection) -> None:
    for table, definitions in _GRAPH_COLUMNS.items():
        existing = {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        }
        for definition in definitions:
            name = definition.split()[0]
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _create_graph_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_capability_aliases_capability
            ON capability_aliases(capability_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_status
            ON decisions(decision_status);
        CREATE INDEX IF NOT EXISTS idx_implementations_status
            ON implementations(historical_status, runtime_status);
        CREATE INDEX IF NOT EXISTS idx_relationships_source
            ON relationships(source_node_type, source_node_id);
        CREATE INDEX IF NOT EXISTS idx_relationships_target
            ON relationships(target_node_type, target_node_id);
        CREATE INDEX IF NOT EXISTS idx_relationships_type
            ON relationships(relationship_type);
        CREATE INDEX IF NOT EXISTS idx_graph_provenance_node
            ON graph_provenance(node_type, node_id);
        CREATE INDEX IF NOT EXISTS idx_graph_provenance_source
            ON graph_provenance(source_item_id);
        CREATE INDEX IF NOT EXISTS idx_ownership_role
            ON ownership_assignments(ownership_role);
        CREATE INDEX IF NOT EXISTS idx_performance_capability
            ON performance_metrics(capability_id, implementation_id);
        CREATE INDEX IF NOT EXISTS idx_guard_runs_signature
            ON guard_runs(logical_signature);
        CREATE INDEX IF NOT EXISTS idx_guard_runs_gate
            ON guard_runs(gate);
        CREATE INDEX IF NOT EXISTS idx_guard_conflicts_run
            ON guard_conflicts(run_id);
        """
    )


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
    _ensure_columns(connection)
    _create_graph_indexes(connection)
    expected = {
        "INDEX_SCHEMA_VERSION": INDEX_SCHEMA_VERSION,
        "PARSER_VERSION": PARSER_VERSION,
        "GUARD_RULESET_VERSION": GUARD_RULESET_VERSION,
    }
    existing = dict(connection.execute("SELECT key, value FROM schema_metadata"))
    schema_value = existing.get("INDEX_SCHEMA_VERSION")
    if schema_value is not None and int(schema_value) > int(INDEX_SCHEMA_VERSION):
        raise RuntimeError(
            f"unsupported index schema {schema_value}; expected {INDEX_SCHEMA_VERSION}"
        )
    connection.executemany(
        "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
        expected.items(),
    )
    connection.commit()
