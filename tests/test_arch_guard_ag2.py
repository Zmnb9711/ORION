from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from tools.orion_arch_guard.cli import main
from tools.orion_arch_guard.fingerprints import canonical_sha256
from tools.orion_arch_guard.graph import CapabilityGraph, GraphBuilder
from tools.orion_arch_guard.graph_seed import (
    EVIDENCE_SEEDS,
    EXTRA_RELATIONSHIPS,
    IMPLEMENTATION_SEEDS,
    MECHANISM_SEEDS,
    OWNERSHIP_SEEDS,
)
from tools.orion_arch_guard.schema import connect_index, migrate

_COMMIT = re.compile(r"[0-9a-fA-F]{7,40}")


def _all_seed_refs() -> set[str]:
    refs: set[str] = set()
    for seed in IMPLEMENTATION_SEEDS:
        refs.update(str(value) for value in seed.get("commits", []))
        refs.update(str(value) for value in seed.get("decisions", []))
        refs.update(str(value) for value in seed.get("evidence", []))
    for collection in (MECHANISM_SEEDS, EXTRA_RELATIONSHIPS, OWNERSHIP_SEEDS):
        for seed in collection:
            refs.update(str(value) for value in seed.get("refs", []))
    return refs


def _insert_source(connection: sqlite3.Connection, source_id: str, path: Path) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO source_snapshots(
            snapshot_id, manifest_sha256, manifest_generated_at_utc,
            indexed_at_utc, source_count, metadata_json
        ) VALUES ('fixture-snapshot', ?, '2026-01-01T00:00:00Z',
                  '2026-01-01T00:00:00Z', 3, '{}')
        """,
        ("A" * 64,),
    )
    connection.execute(
        """
        INSERT INTO sources(
            source_id, source_type, path_reference, exists_flag, size_bytes,
            sha256, mtime_utc, format, privacy_class, discovery_method,
            metadata_json, manifest_snapshot, availability, indexed_sha256,
            indexed_at_utc, parser_version
        ) VALUES (?, 'fixture', ?, 1, 1, ?, '2026-01-01T00:00:00Z',
                  'fixture', 'PROJECT_GIT', 'test', '{}', 'fixture-snapshot',
                  'AVAILABLE', ?, '2026-01-01T00:00:00Z', '3')
        """,
        (source_id, str(path), canonical_sha256(str(path)), canonical_sha256(str(path))),
    )


def _insert_item(
    connection: sqlite3.Connection,
    *,
    item_id: str,
    source_id: str,
    native_id: str,
    item_type: str,
    ordinal: int,
    pointer: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO source_items(
            item_id, source_id, native_id, parent_native_id, parent_item_id,
            thread_key, item_type, timestamp_utc, author_or_role, ordinal,
            content_sha256, bounded_preview, metadata_json, privacy_class,
            source_pointer_json
        ) VALUES (?, ?, ?, NULL, NULL, ?, ?, '2026-01-01T00:00:00Z',
                  NULL, ?, ?, ?, '{}', 'PROJECT_GIT', ?)
        """,
        (
            item_id,
            source_id,
            native_id,
            f"fixture:{item_type}",
            item_type,
            ordinal,
            canonical_sha256([item_id, native_id]),
            native_id,
            json.dumps(pointer),
        ),
    )


def _decision_row(decision_id: str) -> str:
    superseded = "—"
    if decision_id == "D28":
        superseded = "D34/D65"
    elif decision_id == "D29":
        superseded = "D44/D67"
    elif decision_id == "D30":
        superseded = "D65"
    elif decision_id == "D50":
        superseded = "D51/D52"
    area = {
        "D15": "Settings",
        "D28": "STT",
        "D34": "Whisper",
        "D40": "Context",
        "D50": "Language",
        "D51": "Language",
        "D52": "Profiles",
        "D62": "Pilot KB",
        "D65": "STT",
        "D66": "PTT",
        "D68": "MODEL C",
        "D71": "Development process",
        "D72": "Informational UX",
        "D73": "Development process",
        "D74": "Development process",
    }.get(decision_id, "Product")
    return (
        f"| {decision_id} | 2026-01-01 | {area} | Exact decision {decision_id} | "
        f"User | Explicit | Historical | Current | IMPLEMENTED | {superseded} | Git | VERY_HIGH |"
    )


def _fixture_database(tmp_path: Path) -> Path:
    database = tmp_path / "private" / "index.sqlite3"
    document = tmp_path / "decision-register.md"
    lines = [_decision_row(f"D{number:02d}") for number in range(1, 75)]
    document.write_text("\n".join(lines) + "\n", encoding="utf-8")
    connection = connect_index(database)
    migrate(connection)
    _insert_source(connection, "fixture-doc", document)
    _insert_source(connection, "fixture-git", tmp_path / "repo")
    _insert_source(connection, "fixture-evidence", tmp_path / "evidence")
    for ordinal, decision_id in enumerate(f"D{number:02d}" for number in range(1, 75)):
        _insert_item(
            connection,
            item_id=f"document:decision:{decision_id}",
            source_id="fixture-doc",
            native_id=decision_id,
            item_type="decision_register_row",
            ordinal=ordinal,
            pointer={
                "source_id": "fixture-doc",
                "source_type": "project_document",
                "path": str(document),
                "line_start": ordinal + 1,
                "line_end": ordinal + 1,
                "decision_id": decision_id,
            },
        )
    commit_refs = sorted(ref.casefold() for ref in _all_seed_refs() if _COMMIT.fullmatch(ref))
    full_refs = {ref for ref in commit_refs if len(ref) == 40}
    canonical_refs = {
        next((full for full in full_refs if full.startswith(ref)), ref + ("0" * (40 - len(ref))))
        if len(ref) < 40
        else ref
        for ref in commit_refs
    }
    for ordinal, full in enumerate(sorted(canonical_refs)):
        _insert_item(
            connection,
            item_id=f"git:commit:{full}",
            source_id="fixture-git",
            native_id=full,
            item_type="git_commit",
            ordinal=ordinal,
            pointer={
                "source_id": "fixture-git",
                "source_type": "git_repository",
                "path": str(tmp_path / "repo"),
                "commit_sha": full,
            },
        )
    for ordinal, seed in enumerate(EVIDENCE_SEEDS):
        _insert_item(
            connection,
            item_id=str(seed["item"]),
            source_id="fixture-evidence",
            native_id=str(seed["item"]).removeprefix("evidence:"),
            item_type="evidence_archive",
            ordinal=ordinal,
            pointer={
                "source_id": "fixture-evidence",
                "source_type": "evidence_zip",
                "path": str(tmp_path / f"{seed['id']}.zip"),
                "source_sha256": str(seed["item"]).removeprefix("evidence:"),
            },
        )
    connection.commit()
    connection.close()
    return database


def _build(tmp_path: Path) -> tuple[Path, Any]:
    database = _fixture_database(tmp_path)
    builder = GraphBuilder(database)
    try:
        result = builder.build()
    finally:
        builder.close()
    return database, result


def _ids(items: Iterable[dict[str, Any]], key: str) -> set[str]:
    return {str(item[key]) for item in items}


def test_taxonomy_aliases_and_parent_child_are_stable(tmp_path: Path) -> None:
    database, result = _build(tmp_path)
    graph = CapabilityGraph(database)
    try:
        natural = graph.capability("aircraft informational response")
        speechkit = graph.capability("RecognizeStreaming")
        takeoff = graph.capability("TAKEOFF")
    finally:
        graph.close()

    assert result.capabilities == 74
    assert natural and natural["capability_id"] == "NATURAL_INFORMATIONAL_PRESENTATION"
    assert speechkit and speechkit["capability_id"] == "SPEECHKIT_STT"
    assert takeoff and "TOWER" in takeoff["parents"]


def test_all_decisions_and_supersession_rejection_edges_have_provenance(tmp_path: Path) -> None:
    database, result = _build(tmp_path)
    connection = sqlite3.connect(database)
    try:
        decision_ids = {
            row[0] for row in connection.execute("SELECT decision_id FROM decisions")
        }
        supersession = connection.execute(
            """
            SELECT COUNT(*) FROM relationships
            WHERE relationship_type = 'SUPERSEDES'
            """
        ).fetchone()[0]
        rejection = connection.execute(
            "SELECT COUNT(*) FROM relationships WHERE relationship_type = 'REJECTS'"
        ).fetchone()[0]
        orphan_hard = connection.execute(
            """
            SELECT COUNT(*) FROM decisions decision
            WHERE NOT EXISTS (
                SELECT 1 FROM graph_provenance provenance
                WHERE provenance.node_type='DECISION'
                  AND provenance.node_id=decision.decision_id
                  AND provenance.source_item_id IS NOT NULL
            )
            """
        ).fetchone()[0]
        unsupported = connection.execute(
            "SELECT COUNT(*) FROM relationships WHERE confidence IN ('', 'UNKNOWN') OR provenance_json IN ('', '{}')"
        ).fetchone()[0]
    finally:
        connection.close()

    assert result.decisions == 74
    assert decision_ids == {f"D{number:02d}" for number in range(1, 75)}
    assert supersession >= 7
    assert rejection >= 3
    assert orphan_hard == 0
    assert unsupported == 0


def test_stage6a_and_current_aircraft_overlap_without_preference(tmp_path: Path) -> None:
    database, _result = _build(tmp_path)
    graph = CapabilityGraph(database)
    try:
        for capability in (
            "AIRCRAFT_IDENTITY",
            "LIVE_DCS_FACT_PRESENTATION",
            "NATURAL_INFORMATIONAL_PRESENTATION",
        ):
            result = graph.related(capability)
            assert result
            implementations = _ids(result["implementations"], "implementation_id")
            assert "STAGE6A_FLIGHTCONTEXT_REALTIME" in implementations
            assert "CURRENT_AIRCRAFT_IDENTITY_QUERY" in implementations
            assert result["architecture_gate_result"] is None
        aircraft = graph.related("AIRCRAFT_IDENTITY")
        natural = graph.related("NATURAL_INFORMATIONAL_PRESENTATION")
    finally:
        graph.close()

    assert aircraft
    evidence = _ids(aircraft["evidence"], "evidence_id")
    assert {"STAGE6A_FIELD_20260825", "AIRCRAFT_FA18_FIELD", "AIRCRAFT_F5_FIELD"} <= evidence
    assert natural
    assert {
        "CORE_FACT_BINDING",
        "PLACEHOLDER_FACT_VALIDATION",
        "PERSISTENT_REALTIME_SESSION",
    } <= _ids(natural["mechanisms"], "mechanism_id")
    assert all(item["strengths"] for item in natural["mechanisms"])
    assert {
        item["relationship_type"] for item in natural["relationships"]
    } >= {"FIELD_PROVEN_BY", "REUSES_MECHANISM"}


def test_required_historical_lineages_and_negative_classifications(tmp_path: Path) -> None:
    database, _result = _build(tmp_path)
    graph = CapabilityGraph(database)
    try:
        ptt = graph.related("PTT")
        language = graph.related("LANGUAGE_POLICY")
        stt = graph.related("STT")
        phraseology = graph.related("PHRASEOLOGY")
        atc = graph.related("ATC")
    finally:
        graph.close()

    assert ptt and {
        "PACKET_GAP_EOU_HEURISTIC",
        "UDP7082_AUTHORITATIVE_EOU",
        "SRS_CANDIDATE_BUFFERING_IMPLEMENTATION",
        "CADENCE_AWARE_TX_LIVENESS_IMPLEMENTATION",
    } <= _ids(ptt["implementations"], "implementation_id")
    packet_gap = next(
        item for item in ptt["mechanisms"] if item["mechanism_id"] == "PACKET_GAP_EOU"
    )
    assert packet_gap["defects"]
    assert language and {
        "HARD_FOUR_LANGUAGE_MODES",
        "AUTOMATIC_INPUT_LANGUAGE_POLICY",
        "COMMUNICATION_PROFILE_INFRASTRUCTURE",
    } <= _ids(language["implementations"], "implementation_id")
    assert stt and {
        "WHISPER_STT_WORKER",
        "SPEECHKIT_V3_EXTERNAL_EOU_STT",
    } <= _ids(stt["implementations"], "implementation_id")
    whisper = next(
        item for item in stt["implementations"] if item["implementation_id"] == "WHISPER_STT_WORKER"
    )
    assert whisper["runtime_status"] == "EXPLICITLY_REMOVED"
    assert phraseology and {
        "PILOT_PHRASEOLOGY_TEST_CORPUS",
        "OSU_PROTECTED_PHRASEOLOGY",
    } <= _ids(phraseology["implementations"], "implementation_id")
    pilot = next(
        item
        for item in phraseology["implementations"]
        if item["implementation_id"] == "PILOT_PHRASEOLOGY_TEST_CORPUS"
    )
    assert pilot["metadata"]["kb_scope"] == "TEST_CORPUS_ONLY"
    assert atc and {
        "PURE_TAKEOFF_MODEL_C",
        "PERSISTENT_ATC_SESSION_IMPLEMENTATION",
        "ATC_STATUS_QUERY_IMPLEMENTATION",
    } <= _ids(atc["implementations"], "implementation_id")


def test_graph_idempotence_and_incremental_source_update(tmp_path: Path) -> None:
    database, first = _build(tmp_path)
    builder = GraphBuilder(database)
    try:
        second = builder.build()
        connection = builder.connection
        commit_item = connection.execute(
            "SELECT item_id FROM source_items WHERE item_type='git_commit' ORDER BY item_id LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE source_items SET content_sha256 = ? WHERE item_id = ?",
            ("F" * 64, commit_item),
        )
        connection.commit()
        third = builder.build()
    finally:
        builder.close()

    assert first.reused is False
    assert second.reused is True
    assert second.relationships == first.relationships
    assert third.reused is False
    assert third.relationships == first.relationships


def test_capability_cli_and_explain_return_exact_pointers(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    database, _result = _build(tmp_path)

    assert main(["related", "--capability", "natural response", "--database", str(database)]) == 0
    related_output = json.loads(capsys.readouterr().out)
    assert related_output["capability"]["capability_id"] == "NATURAL_INFORMATIONAL_PRESENTATION"
    assert related_output["architecture_gate_result"] is None
    assert related_output["implementations"][0]["provenance"][0]["source_pointer"]

    assert main([
        "explain",
        "--implementation",
        "CURRENT_AIRCRAFT_IDENTITY_QUERY",
        "--database",
        str(database),
    ]) == 0
    explain_output = json.loads(capsys.readouterr().out)
    assert explain_output["implementation"]["runtime_status"] == "CURRENT"
    assert explain_output["provenance"]
    assert explain_output["architecture_gate_result"] is None
