from __future__ import annotations

import json
import sqlite3
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path

from tools.orion_arch_guard.config import SourceConfig
from tools.orion_arch_guard.cli import main
from tools.orion_arch_guard.fingerprints import file_record, sha256_file
from tools.orion_arch_guard.indexing import index_manifest
from tools.orion_arch_guard.manifest import build_manifest, write_manifest
from tools.orion_arch_guard.models import PrivacyClass, SourceType
from tools.orion_arch_guard.queries import HistoryIndex
from tools.orion_arch_guard.schema import (
    GUARD_RULESET_VERSION,
    INDEX_SCHEMA_VERSION,
    PARSER_VERSION,
    connect_index,
    migrate,
)


def _config(tmp_path: Path) -> SourceConfig:
    repository = tmp_path / "repo"
    repository.mkdir()
    return SourceConfig(
        repository_root=repository,
        output_path=tmp_path / "private" / "source-manifest.json",
        chatgpt_archive_roots=(tmp_path / "chatgpt",),
        codex_history_roots=(tmp_path / "codex",),
        evidence_roots=(tmp_path / "evidence",),
        runtime_log_roots=(tmp_path / "runtime",),
        release_roots=(repository,),
        index_path=tmp_path / "private" / "index.sqlite3",
    )


def _record(path: Path, source_type: SourceType, privacy: PrivacyClass):  # noqa: ANN202
    return file_record(
        path,
        source_type=source_type,
        privacy_class=privacy,
        discovery_method="ag1-test",
        format_name={
            SourceType.CHATGPT_ARCHIVE: "chatgpt-export/zip",
            SourceType.CODEX_ROLLOUT: "codex-rollout/jsonl",
            SourceType.EVIDENCE_ZIP: "orion-test-evidence/zip",
            SourceType.PROJECT_DOCUMENT: "markdown",
        }.get(source_type),
    )


def _run_index(config: SourceConfig, *sources):  # noqa: ANN202
    manifest = build_manifest(config, sources)
    write_manifest(config.output_path, manifest)
    return index_manifest(
        manifest,
        config.resolved_index_path,
        manifest_sha256=sha256_file(config.output_path),
    )


def test_schema_and_migration_seams(tmp_path: Path) -> None:
    database = tmp_path / "index.sqlite3"
    connection = connect_index(database)
    migrate(connection)
    migrate(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    metadata = dict(connection.execute("SELECT key, value FROM schema_metadata"))

    assert {
        "sources",
        "source_items",
        "source_snapshots",
        "schema_metadata",
        "capabilities",
        "decisions",
        "implementations",
        "mechanisms",
        "evidence",
        "performance_metrics",
        "relationships",
        "guard_runs",
        "guard_conflicts",
    } <= tables
    assert metadata == {
        "INDEX_SCHEMA_VERSION": INDEX_SCHEMA_VERSION,
        "PARSER_VERSION": PARSER_VERSION,
        "GUARD_RULESET_VERSION": GUARD_RULESET_VERSION,
    }


def test_chatgpt_tree_chronology_exact_pointer_and_secret_redaction(tmp_path: Path) -> None:
    config = _config(tmp_path)
    archive_path = tmp_path / "chatgpt.zip"
    conversation_id = "conversation-1"
    mapping = {
        "root": {"id": "root", "parent": None, "children": ["u1"], "message": None},
        "u1": {
            "id": "u1",
            "parent": "root",
            "children": ["a1", "alt"],
            "message": {
                "id": "m-u1",
                "author": {"role": "user"},
                "create_time": 1,
                "content": {"parts": ["Authorization: Bearer SUPER_SECRET_TOKEN_123456789"]},
            },
        },
        "a1": {
            "id": "a1",
            "parent": "u1",
            "children": [],
            "message": {
                "id": "m-a1",
                "author": {"role": "assistant"},
                "create_time": 2,
                "content": {"parts": ["Principal answer"]},
            },
        },
        "alt": {
            "id": "alt",
            "parent": "u1",
            "children": [],
            "message": {
                "id": "m-alt",
                "author": {"role": "assistant"},
                "create_time": 1.5,
                "content": {"parts": ["Abandoned alternative"]},
            },
        },
    }
    payload = [{
        "id": conversation_id,
        "title": "ORION history",
        "create_time": 1,
        "update_time": 2,
        "current_node": "a1",
        "mapping": mapping,
    }]
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("conversations.json", json.dumps(payload))
    source = _record(
        archive_path,
        SourceType.CHATGPT_ARCHIVE,
        PrivacyClass.PRIVATE_PRIMARY_HISTORY,
    )

    _run_index(config, source)
    index = HistoryIndex(config.resolved_index_path)
    try:
        conversation = index.find_native(conversation_id, item_type="chatgpt_conversation")
        user_item = index.find_native("u1", item_type="chatgpt_message")[0]
        answer = index.find_native("a1", item_type="chatgpt_message")[0]
        alternative = index.find_native("alt", item_type="chatgpt_message")[0]
        neighbors = index.neighbors(answer["item_id"])
    finally:
        index.close()

    assert len(conversation) == 1
    assert user_item["metadata"]["branch_classification"] == "principal"
    assert alternative["metadata"]["branch_classification"] == "alternative"
    assert neighbors["previous"]["native_id"] == "u1"
    assert user_item["source_pointer"]["conversation_id"] == conversation_id
    assert user_item["source_pointer"]["node_id"] == "u1"
    encoded = config.resolved_index_path.read_bytes()
    assert b"SUPER_SECRET_TOKEN" not in encoded
    assert b"Authorization: Bearer" not in encoded
    assert b"Authorization:" not in encoded


def test_codex_jsonl_native_identity_and_neighbor_range(tmp_path: Path) -> None:
    config = _config(tmp_path)
    rollout = tmp_path / "rollout-2026-01-01T00-00-00-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jsonl"
    events = [
        {"timestamp": "2026-01-01T00:00:00Z", "type": "message", "payload": {"id": "one", "role": "user", "content": "first"}},
        {"timestamp": "2026-01-01T00:00:01Z", "type": "message", "payload": {"id": "two", "role": "assistant", "content": "second", "parent_id": "one"}},
        {"timestamp": "2026-01-01T00:00:02Z", "type": "event", "payload": {"id": "three", "content": "third"}},
    ]
    rollout.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    source = _record(rollout, SourceType.CODEX_ROLLOUT, PrivacyClass.PRIVATE_PRIMARY_HISTORY)

    _run_index(config, source)
    index = HistoryIndex(config.resolved_index_path)
    try:
        second = index.find_native("two")[0]
        neighbor = index.neighbors(second["item_id"])
        selected_range = index.thread_range(second["item_id"], before=1, after=1)
    finally:
        index.close()

    assert second["source_pointer"]["jsonl_ordinal"] == 1
    assert neighbor["previous"]["native_id"] == "one"
    assert neighbor["next"]["native_id"] == "three"
    assert [item["native_id"] for item in selected_range] == ["one", "two", "three"]


def test_git_all_commits_changed_deleted_and_renamed_paths(tmp_path: Path) -> None:
    config = _config(tmp_path)
    repository = config.repository_root
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "guard@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Guard"], cwd=repository, check=True)
    old = repository / "old.txt"
    old.write_text("line\n", encoding="utf-8")
    subprocess.run(["git", "add", "old.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "add old"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "mv", "old.txt", "new.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "rename old"], cwd=repository, check=True, capture_output=True)
    (repository / "new.txt").unlink()
    subprocess.run(["git", "add", "-u"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "delete new"], cwd=repository, check=True, capture_output=True)
    from tools.orion_arch_guard.discovery import discover_git

    source = discover_git(config)
    _run_index(config, source)
    index = HistoryIndex(config.resolved_index_path)
    try:
        status = index.status()
        old_history = index.git_path_history("old.txt")
        new_history = index.git_path_history("new.txt")
    finally:
        index.close()

    assert status["items_by_type"]["git_commit"] == 3
    assert any(item["metadata"]["lineage_hint"] == "explicit_rename" for item in old_history)
    assert any(item["metadata"]["change_type"] == "D" for item in new_history)


def test_evidence_metadata_has_event_count_but_no_audio_body(tmp_path: Path) -> None:
    config = _config(tmp_path)
    evidence = tmp_path / "ORION-Test-Evidence-20260902-120000.zip"
    with zipfile.ZipFile(evidence, "w") as archive:
        archive.writestr("events.jsonl", '{"event":"one"}\n{"event":"two"}\n')
        archive.writestr(
            "session-summary.txt",
            "radio_stt_provider=speechkit_v3_external_eou\nhuman_review=PASS\n",
        )
        archive.writestr("secret.wav", b"RIFF PRIVATE AUDIO")
    source = replace(
        _record(evidence, SourceType.EVIDENCE_ZIP, PrivacyClass.PRIVATE_EVIDENCE),
        metadata={"build_sha": "A" * 40, "explicit_evidence_kind": "FIELD"},
    )

    _run_index(config, source)
    index = HistoryIndex(config.resolved_index_path)
    try:
        item = index.find_native(source.sha256 or "")[0]
    finally:
        index.close()

    assert item["metadata"]["event_count"] == 2
    assert item["metadata"]["radio_stt_provider"] == "speechkit_v3_external_eou"
    assert item["metadata"]["human_review"] == "PASS"
    assert item["metadata"]["raw_audio_ingested"] is False
    assert b"RIFF PRIVATE AUDIO" not in config.resolved_index_path.read_bytes()


def test_decision_rows_sections_and_exact_lines(tmp_path: Path) -> None:
    config = _config(tmp_path)
    document = config.repository_root / "docs" / "orion-master-decision-register-2026-09-01.md"
    document.parent.mkdir()
    rows = "\n".join(f"| D{number:02d} | Decision {number} |" for number in range(1, 76))
    document.write_text(f"# Register\n\n{rows}\n", encoding="utf-8")
    source = _record(document, SourceType.PROJECT_DOCUMENT, PrivacyClass.PROJECT_GIT)

    _run_index(config, source)
    index = HistoryIndex(config.resolved_index_path)
    try:
        d71 = index.find_native("D71", item_type="decision_register_row")
        d72 = index.find_native("D72", item_type="decision_register_row")
        d73 = index.find_native("D73", item_type="decision_register_row")
        d74 = index.find_native("D74", item_type="decision_register_row")
        status = index.status()
    finally:
        index.close()

    assert len(d71) == len(d72) == len(d73) == len(d74) == 1
    assert d71[0]["source_pointer"]["line_start"] == 73
    assert d73[0]["source_pointer"]["line_start"] == 75
    assert d74[0]["source_pointer"]["line_start"] == 76
    assert status["items_by_type"]["decision_register_row"] == 75


def test_release_artifacts_are_bounded_and_addressable(tmp_path: Path) -> None:
    config = _config(tmp_path)
    release = tmp_path / "release-test"
    release.mkdir()
    installer = release / "ORION-Setup.exe"
    installer.write_bytes(b"installer-placeholder")
    marker = release / "Core" / "build-identity.json"
    marker.parent.mkdir()
    marker.write_text(json.dumps({"sha": "A" * 40}), encoding="utf-8")
    from tools.orion_arch_guard.fingerprints import bounded_directory_record

    source = bounded_directory_record(
        release,
        source_type=SourceType.RELEASE_TREE,
        privacy_class=PrivacyClass.PROJECT_GIT,
        discovery_method="test",
        entries=[],
        metadata={"release_name": release.name},
    )

    _run_index(config, source)
    index = HistoryIndex(config.resolved_index_path)
    try:
        artifacts = index.connection.execute(
            "SELECT native_id, metadata_json FROM source_items WHERE item_type='release_artifact' ORDER BY native_id"
        ).fetchall()
    finally:
        index.close()

    assert [row[0] for row in artifacts] == [
        "Core/build-identity.json",
        "ORION-Setup.exe",
    ]


def test_idempotent_reindex_relocation_change_snapshot_missing_and_dedup(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first_path = tmp_path / "one.log"
    first_path.write_text("first", encoding="utf-8")
    first = _record(first_path, SourceType.RUNTIME_ARTIFACT, PrivacyClass.PRIVATE_RUNTIME_LOG)

    first_result = _run_index(config, first)
    second_result = _run_index(config, first)
    relocated_path = tmp_path / "two.log"
    relocated_path.write_text("first", encoding="utf-8")
    relocated = _record(relocated_path, SourceType.RUNTIME_ARTIFACT, PrivacyClass.PRIVATE_RUNTIME_LOG)
    _run_index(config, first, relocated)
    first_path.write_text("changed", encoding="utf-8")
    changed = _record(first_path, SourceType.RUNTIME_ARTIFACT, PrivacyClass.PRIVATE_RUNTIME_LOG)
    _run_index(config, changed)
    missing = replace(changed, exists=False, size_bytes=None, sha256=None, mtime_utc=None)
    _run_index(config, missing)

    connection = sqlite3.connect(config.resolved_index_path)
    try:
        item_count = connection.execute("SELECT COUNT(*) FROM source_items").fetchone()[0]
        snapshots = connection.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0]
        locations = connection.execute(
            "SELECT COUNT(*) FROM source_locations WHERE source_id = ?", (first.source_id,)
        ).fetchone()[0]
        availability = connection.execute(
            "SELECT availability FROM sources WHERE source_id = ?", (changed.source_id,)
        ).fetchone()[0]
    finally:
        connection.close()

    assert first_result.items_upserted == 1
    assert second_result.items_upserted == 0
    assert item_count == 2
    assert snapshots >= 3
    assert locations == 2
    assert availability == "UNAVAILABLE"


def test_database_default_is_outside_repository(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    repository = tmp_path / "repo"
    repository.mkdir()

    config = SourceConfig.defaults(repository)

    assert config.resolved_index_path == local / "ORION" / "development" / "architecture-guard" / "index.sqlite3"
    assert not config.resolved_index_path.is_relative_to(repository)


def test_status_and_lookup_cli(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    config = _config(tmp_path)
    document = config.repository_root / "docs" / "decision.md"
    document.parent.mkdir()
    document.write_text("# One\n", encoding="utf-8")
    source = _record(document, SourceType.PROJECT_DOCUMENT, PrivacyClass.PROJECT_GIT)
    _run_index(config, source)

    assert main(["status", "--database", str(config.resolved_index_path)]) == 0
    status_output = capsys.readouterr().out
    item_id = sqlite3.connect(config.resolved_index_path).execute(
        "SELECT item_id FROM source_items LIMIT 1"
    ).fetchone()[0]
    assert main([
        "lookup", "--database", str(config.resolved_index_path), "--item", item_id
    ]) == 0
    lookup_output = capsys.readouterr().out

    assert '"authoritative": false' in status_output
    assert item_id in lookup_output
