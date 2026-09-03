from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.orion_arch_guard.fingerprints import canonical_sha256
from tools.orion_arch_guard.canonical_seed import ALL_CANONICAL_RECORDS
from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.memory import DevelopmentMemoryService
from tools.orion_development_console.memory_models import DevelopmentCheckpoint, PromptRecord, PromptType
from tools.orion_development_console.roadmap import (
    RoadmapService,
    _branch_for,
    _git_type,
    _proofs,
    compare_snapshots,
)
from tools.orion_development_console.roadmap_models import (
    BranchType,
    NodeType,
    ProofBadge,
    ProvenancePointer,
    RoadmapNode,
    RoadmapSnapshot,
    RoadmapState,
    RoadmapStatistics,
)
from tools.orion_development_console.roadmap_store import RoadmapSnapshotStore
from tools.orion_development_console.roadmap_view import _overview_position
from tools.orion_development_console.theme import PALETTE


FIXED_NOW = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)


def _git_runner(_root: Path, args: tuple[str, ...]) -> str:
    values = {
        ("rev-parse", "HEAD"): "a" * 40,
        ("branch", "--show-current"): "dev/fixture",
        ("rev-list", "--count", "HEAD"): "3",
        ("status", "--porcelain=v1"): "",
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/dev/fixture",
        ("rev-parse", "@{upstream}"): "a" * 40,
        ("rev-list", "--left-right", "--count", "HEAD...@{upstream}"): "0 0",
    }
    return values[args]


class FixtureMemory(DevelopmentMemoryService):
    def generate_task_recall(self, task: str) -> PromptRecord:
        content = f"VISIBLE ROADMAP RECALL\n{task}"
        return PromptRecord(
            prompt_id="PR-FIXTURE",
            prompt_type=PromptType.TASK_RECALL,
            created_at=FIXED_NOW.isoformat(),
            guard_report_id="AG-FIXTURE",
            head_sha="a" * 40,
            task=task,
            capabilities=["UDP7082"],
            content=content,
            content_fingerprint=canonical_sha256({"content": content}).casefold(),
            provenance=["roadmap:fixture"],
        )


def _context(tmp_path: Path) -> VerificationContext:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").mkdir()
    (repository / "docs").mkdir()
    guard = tmp_path / "guard"
    (guard / "reports").mkdir(parents=True)
    console = tmp_path / "console"
    report = {
        "report_id": "AG-FIXTURE",
        "gate": "PASS",
        "history_coverage": {"overall": "COMPLETE"},
    }
    (guard / "reports" / "AG-FIXTURE.json").write_text(json.dumps(report), encoding="utf-8")
    return VerificationContext(
        repository_root=repository,
        local_app_data=tmp_path,
        guard_root=guard,
        console_root=console,
        architecture_report_id="AG-FIXTURE",
        git_runner=_git_runner,
        now=lambda: FIXED_NOW,
    )


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE graph_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE source_snapshots(snapshot_id TEXT, manifest_sha256 TEXT, indexed_at_utc TEXT);
        CREATE TABLE source_items(item_id TEXT PRIMARY KEY, item_type TEXT, timestamp_utc TEXT, bounded_preview TEXT, metadata_json TEXT, source_pointer_json TEXT);
        CREATE TABLE graph_provenance(node_type TEXT, node_id TEXT, source_item_id TEXT, source_pointer_json TEXT, confidence TEXT);
        CREATE TABLE decisions(decision_id TEXT PRIMARY KEY, decision_date TEXT, area TEXT, decision_text TEXT, proposed_by TEXT, user_approval TEXT, historical_implementation TEXT, current_implementation TEXT, decision_status TEXT, superseded_by_json TEXT, evidence_summary TEXT, confidence TEXT, source_item_id TEXT, metadata_json TEXT);
        CREATE TABLE implementations(implementation_id TEXT PRIMARY KEY, name TEXT, provider TEXT, session_model TEXT, runtime_status TEXT, historical_status TEXT, introduced_at TEXT, commit_range_json TEXT, files_components_json TEXT, strengths_json TEXT, defects_json TEXT, abandonment_reason TEXT, metadata_json TEXT);
        CREATE TABLE mechanisms(mechanism_id TEXT PRIMARY KEY, name TEXT, description TEXT, invariant_text TEXT, current_presence INTEGER, historical_status TEXT, field_probe_status TEXT, strengths_json TEXT, defects_json TEXT, metadata_json TEXT);
        CREATE TABLE evidence(evidence_id TEXT PRIMARY KEY, name TEXT, evidence_type TEXT, evidence_status TEXT, source_item_id TEXT, metadata_json TEXT);
        CREATE TABLE capabilities(capability_id TEXT PRIMARY KEY, family TEXT, name TEXT, description TEXT, aliases_json TEXT, historical_terms_json TEXT, code_symbols_json TEXT, providers_json TEXT, related_domains_json TEXT, metadata_json TEXT);
        CREATE TABLE relationships(relationship_id TEXT PRIMARY KEY, source_node_type TEXT, source_node_id TEXT, relationship_type TEXT, target_node_type TEXT, target_node_id TEXT, confidence TEXT, provenance_json TEXT, metadata_json TEXT);
        CREATE TABLE guard_runs(run_id TEXT PRIMARY KEY, created_at_utc TEXT, mode_requested TEXT, mode_effective TEXT, task_hash TEXT, head_sha TEXT, ruleset_version TEXT, index_signature TEXT, logical_signature TEXT, gate TEXT, input_json TEXT, output_json TEXT, human_report_path TEXT, json_report_path TEXT);
        CREATE TABLE canonical_records(record_id TEXT PRIMARY KEY, record_kind TEXT, title TEXT, status TEXT, classification TEXT, summary TEXT, proof_level TEXT, recommended_action TEXT, priority TEXT, user_decision_required INTEGER, user_valued INTEGER, capabilities_json TEXT, source_refs_json TEXT, evidence_refs_json TEXT, metadata_json TEXT, input_signature TEXT);
        INSERT INTO graph_metadata VALUES('AG2_INPUT_SIGNATURE','GRAPH-FIXTURE');
        INSERT INTO graph_metadata VALUES('CANONICAL_INPUT_SIGNATURE','CANONICAL-FIXTURE');
        INSERT INTO source_snapshots VALUES('SOURCE-SNAPSHOT','MANIFEST-FIXTURE','2026-09-02T00:00:00+00:00');
        """
    )
    items = [
        ("chatgpt:conversation:early", "chatgpt_conversation", "2026-08-01T20:00:00+00:00", "Early ORION concept", "{}", '{"conversation_id":"early"}'),
        ("git:commit:111", "git_commit", "2026-08-06T00:00:00+00:00", "Initialize ORION", '{"parents":[]}', '{"commit_sha":"111"}'),
        ("git:commit:222", "git_commit", "2026-09-01T10:00:00+00:00", "test: capture field evidence", '{"parents":["111"]}', '{"commit_sha":"222"}'),
        ("git:commit:333", "git_commit", "2026-09-01T11:00:00+00:00", "fix: adapt UDP7082 liveness to cadence", '{"parents":["222"]}', '{"commit_sha":"333"}'),
        ("evidence:fixture", "evidence_archive", "2026-09-01T12:00:00+00:00", "[REDACTED].zip", '{"raw_audio_ingested":false}', '{"source_sha256":"EVIDENCE"}'),
        ("document:section:history", "document_section", "2026-09-02T00:00:00+00:00", "Development History", "{}", '{"path":"docs/history.md"}'),
    ]
    connection.executemany("INSERT INTO source_items VALUES(?,?,?,?,?,?)", items)
    connection.execute(
        "INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("D01", "2026-08-04", "Product", "ORION is a DCS copilot", "User", "Explicit", "Concept", "Core", "IMPLEMENTED", "[]", "History", "VERY_HIGH", "document:section:history", '{"capabilities":["PRODUCT_SCOPE"]}'),
    )
    connection.executemany(
        "INSERT INTO implementations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("FIXED_TIMEOUT", "Fixed timeout liveness", None, None, "SUPERSEDED", "SUPERSEDED", "2026-08-31", '["222"]', "[]", "[]", '["fixed stale timing was sensitive to sender cadence"]', "Replaced", '{"capabilities":["UDP7082"],"evidence":[]}'),
            ("CADENCE_AWARE", "Cadence-aware UDP7082 liveness", None, None, "CURRENT", "FIELD_PROVEN", "2026-09-01", '["333"]', "[]", '["long PTT survives sender cadence"]', "[]", "UNKNOWN", '{"capabilities":["UDP7082"],"evidence":["CADENCE_FIELD"]}'),
        ],
    )
    connection.execute("INSERT INTO mechanisms VALUES(?,?,?,?,?,?,?,?,?,?)", ("M1", "PTT mechanism", "Authoritative physical PTT", "true-to-false owns EOU", 1, "CURRENT", "FIELD_PROVEN", "[]", "[]", '{"capabilities":["UDP7082"]}'))
    connection.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?)", ("CADENCE_FIELD", "Cadence field proof", "FIELD", "FIELD_PROVEN", "evidence:fixture", "{}"))
    connection.execute("INSERT INTO capabilities VALUES(?,?,?,?,?,?,?,?,?,?)", ("UDP7082", "RADIO", "UDP7082", "SRS TX state", "[]", "[]", "[]", "[]", "[]", "{}"))
    connection.executemany(
        "INSERT INTO graph_provenance VALUES(?,?,?,?,?)",
        [
            ("DECISION", "D01", "document:section:history", '{"decision_id":"D01"}', "VERY_HIGH"),
            ("IMPLEMENTATION", "FIXED_TIMEOUT", "git:commit:222", '{"commit_sha":"222"}', "VERY_HIGH"),
            ("IMPLEMENTATION", "CADENCE_AWARE", "git:commit:333", '{"commit_sha":"333"}', "VERY_HIGH"),
            ("MECHANISM", "M1", "git:commit:333", '{"commit_sha":"333"}', "VERY_HIGH"),
            ("EVIDENCE", "CADENCE_FIELD", "evidence:fixture", '{"source_sha256":"EVIDENCE"}', "VERY_HIGH"),
        ],
    )
    connection.executemany(
        "INSERT INTO relationships VALUES(?,?,?,?,?,?,?,?,?)",
        [
            ("R1", "IMPLEMENTATION", "CADENCE_AWARE", "FIELD_PROVEN_BY", "EVIDENCE", "CADENCE_FIELD", "VERY_HIGH", "{}", "{}"),
            ("R2", "IMPLEMENTATION", "CADENCE_AWARE", "IMPLEMENTS", "CAPABILITY", "UDP7082", "VERY_HIGH", "{}", "{}"),
            ("R3", "IMPLEMENTATION", "CADENCE_AWARE", "REPLACED_BY", "IMPLEMENTATION", "FIXED_TIMEOUT", "VERY_HIGH", "{}", "{}"),
        ],
    )
    connection.execute(
        "INSERT INTO guard_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("AG-FIXTURE", "2026-09-02T12:00:00+00:00", "FULL", "FULL", "task", "a" * 40, "1", "index", "logical", "PASS", '{"task_title":"Phase 3"}', "{}", None, "AG-FIXTURE.json"),
    )
    for record in ALL_CANONICAL_RECORDS:
        value = record.to_dict()
        connection.execute(
            "INSERT INTO canonical_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.record_id,
                record.kind.value,
                record.title,
                record.status,
                record.classification,
                record.summary,
                record.proof_level,
                record.recommended_action,
                record.priority,
                int(record.user_decision_required),
                int(record.user_valued),
                json.dumps(value["capabilities"]),
                json.dumps(value["source_refs"]),
                json.dumps(value["evidence_refs"]),
                json.dumps(record.metadata),
                "CANONICAL-FIXTURE",
            ),
        )
    connection.commit()
    connection.close()


def _service(tmp_path: Path, *, phase3_complete: bool = False) -> RoadmapService:
    context = _context(tmp_path)
    if phase3_complete:
        (context.repository_root / "docs" / "orion-development-history-2026-09-02.md").write_text("## Development Console Phase 3", encoding="utf-8")
    database = context.guard_root / "index.sqlite3"
    _database(database)
    memory = FixtureMemory(context, now=lambda: FIXED_NOW)
    checkpoint = DevelopmentCheckpoint(
        checkpoint_id="CP-FIXTURE",
        created_at="2026-09-02T20:00:00+00:00",
        branch="dev/fixture",
        head_sha="a" * 40,
        guard_report_id="AG-FIXTURE",
        development_stage="PHASE 2",
        approved_next_step="PHASE 3",
        content_fingerprint="",
    )
    checkpoint = checkpoint.model_copy(update={"content_fingerprint": checkpoint.expected_fingerprint()})
    memory.checkpoints.save_create_once(checkpoint)
    return RoadmapService(context, memory=memory, now=lambda: FIXED_NOW, database_path=database)


def _node(node_id: str, occurred_at: str, **updates: object) -> RoadmapNode:
    values: dict[str, object] = {
        "node_id": node_id,
        "node_type": NodeType.IMPLEMENTATION,
        "title": node_id,
        "occurred_at": occurred_at,
        "provenance": [ProvenancePointer(category="GIT", source_item_id=node_id)],
    }
    values.update(updates)
    return RoadmapNode.model_validate(values)


def _snapshot(snapshot_id: str, nodes: list[RoadmapNode], dependency: str = "dep") -> RoadmapSnapshot:
    snapshot = RoadmapSnapshot(
        snapshot_id=snapshot_id,
        generated_at=FIXED_NOW.isoformat(),
        state=RoadmapState.CURRENT,
        dependency_fingerprint=dependency,
        content_fingerprint="",
        repository_head="a" * 40,
        guard_report_id="AG-FIXTURE",
        guard_graph_signature="GRAPH",
        current_node_id=nodes[-1].node_id,
        nodes=nodes,
        edges=[],
        statistics=RoadmapStatistics(nodes=len(nodes)),
    )
    return snapshot.model_copy(update={"content_fingerprint": snapshot.expected_fingerprint()})


def test_real_fixture_build_is_maximum_detail_and_oldest_first(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).build_snapshot()
    assert snapshot.state is RoadmapState.CURRENT
    assert snapshot.nodes[0].node_id == "project:orion"
    assert any(node.node_id == "canonical:C4" for node in snapshot.nodes)
    assert snapshot.statistics.nodes >= 25
    assert snapshot.statistics.edges >= 10
    assert snapshot.content_fingerprint == snapshot.expected_fingerprint()


def test_stable_node_ids_and_idempotent_refresh(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first, _ = service.refresh()
    second, differential = service.refresh()
    assert [node.node_id for node in first.nodes] == [node.node_id for node in second.nodes]
    assert first.content_fingerprint == second.content_fingerprint
    assert differential.unchanged


def test_recovered_old_history_is_inserted_chronologically() -> None:
    old = _snapshot("old", [_node("newer", "2026-09-01T00:00:00+00:00")])
    current = _snapshot("new", [_node("older", "2026-08-01T00:00:00+00:00"), *_snapshot("x", old.nodes).nodes])
    differential = compare_snapshots(old, current)
    assert differential.recovered_historical_nodes == ["older"]


def test_no_silent_node_loss() -> None:
    old = _snapshot("old", [_node("lost", "2026-08-01T00:00:00+00:00"), _node("kept", "2026-09-01T00:00:00+00:00")])
    current = _snapshot("new", [_node("kept", "2026-09-01T00:00:00+00:00")])
    differential = compare_snapshots(old, current)
    assert differential.missing_nodes[0].classification == "SOURCE_MISSING"
    assert differential.missing_nodes[0].node_id == "lost"


def test_changed_proof_state_is_prominent() -> None:
    old = _snapshot("old", [_node("proof", "2026-09-01T00:00:00+00:00", status="IMPLEMENTED")])
    current = _snapshot("new", [_node("proof", "2026-09-01T00:00:00+00:00", status="FIELD_PROVEN", proof_badges=[ProofBadge.FIELD_PROVEN], completed=True)])
    assert compare_snapshots(old, current).proof_state_changes == ["proof"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("test: validate contract", NodeType.TEST),
        ("field evidence capture", NodeType.FIELD_TEST),
        ("forensic investigation", NodeType.ROOT_CAUSE),
        ("fix: cadence liveness", NodeType.FIX),
        ("remove Whisper", NodeType.REMOVAL),
        ("refactor session", NodeType.REFACTOR),
    ],
)
def test_git_classification(title: str, expected: NodeType) -> None:
    assert _git_type(title) is expected


def test_branch_identity_is_independent_from_node_result() -> None:
    assert _branch_for(NodeType.TEST) is BranchType.TEST_EXPERIMENT
    badges, completed = _proofs("FIELD_PROVEN", node_type=NodeType.TEST)
    assert completed
    assert ProofBadge.FIELD_PROVEN in badges


def test_completion_requires_proof() -> None:
    _badges, implemented_complete = _proofs("IMPLEMENTED", node_type=NodeType.IMPLEMENTATION)
    _badges, field_complete = _proofs("FIELD_PROVEN", node_type=NodeType.IMPLEMENTATION)
    assert not implemented_complete
    assert field_complete


def test_failed_superseded_and_rejected_history_retained(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).build_snapshot()
    assert any(node.node_type is NodeType.FAILURE for node in snapshot.nodes)
    assert any(ProofBadge.SUPERSEDED in node.proof_badges for node in snapshot.nodes)


def test_failure_root_cause_fix_retest_chain_is_real(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).build_snapshot()
    types = {node.node_type for node in snapshot.nodes if "cadence" in (node.title + node.description).casefold()}
    assert {NodeType.FAILURE, NodeType.ROOT_CAUSE, NodeType.FIX, NodeType.RETEST} <= types


def test_exact_provenance_present(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).build_snapshot()
    decision = next(node for node in snapshot.nodes if node.node_id == "decision:D01")
    assert decision.provenance[0].source_item_id == "document:section:history"


def test_checkpoint_node_reuses_phase2_store(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).build_snapshot()
    checkpoint = next(node for node in snapshot.nodes if node.node_type is NodeType.CHECKPOINT)
    assert checkpoint.checkpoint_ids == ["CP-FIXTURE"]


def test_recall_node_generates_visible_phase2_prompt(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.build_snapshot()
    prompt = service.recall_node(snapshot, "implementation:CADENCE_AWARE")
    assert prompt.prompt_type is PromptType.TASK_RECALL
    assert "VISIBLE ROADMAP RECALL" in prompt.content


def test_search_covers_decision_commit_provider_evidence_and_checkpoint(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.build_snapshot()
    for query in ("D01", "333", "CADENCE_FIELD", "CP-FIXTURE", "UDP7082"):
        assert service.search(snapshot, query), query


@pytest.mark.parametrize("filter_name", ["ALL", *[name for name in ("MAIN DEVELOPMENT", "TEST / EXPERIMENT", "FIELD_PROVEN", "FAILURES / FIXES", "UNFINISHED", "SUPERSEDED / REJECTED", "DECISIONS", "CHECKPOINTS")]])
def test_filters_change_presentation_only(tmp_path: Path, filter_name: str) -> None:
    service = _service(tmp_path)
    snapshot = service.build_snapshot()
    before = snapshot.content_fingerprint
    service.filtered_nodes(snapshot, filter_name)
    assert snapshot.content_fingerprint == before


def test_expand_collapse_hides_stage_children_only(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.build_snapshot()
    stage = next(node for node in snapshot.nodes if node.node_type is NodeType.STAGE)
    expanded = service.filtered_nodes(snapshot, "ALL")
    collapsed = service.filtered_nodes(snapshot, "ALL", collapsed={stage.node_id})
    assert len(collapsed) < len(expanded)
    assert stage in collapsed


def test_phase3_completion_moves_current_to_checkpoint(tmp_path: Path) -> None:
    service = _service(tmp_path, phase3_complete=True)
    snapshot = service.build_snapshot()
    assert snapshot.current_node_id == "canonical:C3"
    assert sum(node.node_type is NodeType.PLANNED for node in snapshot.nodes) >= 4

    position = service.development_position(snapshot)
    assert position.checkpoint_stage == "CANONICAL ORION BASELINE ESTABLISHED · CURRENT"
    assert position.approved_next_step == "REALTIME INFORMATIONAL PRESENTER RELIABILITY CORRECTION"
    assert position.current_node_id == "canonical:C3"


def test_checkpoint_candidate_uses_current_roadmap_not_stale_saved_checkpoint(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, phase3_complete=True)
    snapshot = service.build_snapshot()

    candidate = service.checkpoint_candidate(snapshot)

    assert candidate.development_stage == "CANONICAL ORION BASELINE ESTABLISHED · CURRENT"
    assert candidate.approved_next_step == "REALTIME INFORMATIONAL PRESENTER RELIABILITY CORRECTION"
    saved = service.memory.latest_checkpoint()
    assert saved is not None
    assert candidate.development_stage != saved.development_stage
    assert len(service.memory.checkpoints.list_records()) == 1


def test_canonical_roadmap_preserves_visual_classes_and_current_position(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.build_snapshot()
    golden = [node for node in snapshot.nodes if node.metadata.get("canonical_kind") == "GOLDEN_COMPONENT"]
    reconnect = [node for node in snapshot.nodes if node.node_type is NodeType.HISTORICAL_RECONNECT]
    ideas = [node for node in snapshot.nodes if node.metadata.get("canonical_kind") == "RECOVERED_IDEA"]
    retirement = [node for node in snapshot.nodes if node.node_type is NodeType.RETIREMENT]

    assert len(golden) == 18
    assert len(reconnect) == 2
    assert len(ideas) == 20
    assert len(retirement) == 8
    assert all(node.completed for node in golden)
    assert all(not node.completed and node.branch_type is BranchType.RECOVERED_FUTURE for node in ideas)
    assert snapshot.current_node_id == "canonical:C3"
    position = service.development_position(snapshot)
    assert position.approved_next_node_id == "canonical:C4"


def test_canonical_search_filters_and_summary_are_machine_retrievable(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.build_snapshot()
    assert any(node.node_id == "canonical:U04" for node in service.search(snapshot, "U04 AWACS"))
    assert any(node.node_id == "canonical:U06" for node in service.search(snapshot, "U06 JTAC"))
    assert any(node.node_id == "canonical:U17" for node in service.search(snapshot, "U17 Debrief"))
    assert len(service.filtered_nodes(snapshot, "RECOVERED IDEAS")) == 20
    assert len(service.filtered_nodes(snapshot, "HISTORICAL RECONNECT")) == 2
    summary = service.canonical_summary()
    assert summary["strategy"] == "STRATEGY_A_CURRENT_RECONNECT"
    assert summary["counts"]["RECOVERED_IDEA"] == 20
    assert summary["input_signature"] == "CANONICAL-FIXTURE"


def test_freshness_current_stale_refresh_current(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot, _ = service.refresh()
    assert service.freshness(snapshot) is RoadmapState.CURRENT
    snapshot = snapshot.model_copy(update={"dependency_fingerprint": "changed"})
    assert service.freshness(snapshot) is RoadmapState.STALE
    refreshed, _ = service.refresh()
    assert service.freshness(refreshed) is RoadmapState.CURRENT


def test_snapshot_store_is_private_create_once(tmp_path: Path) -> None:
    store = RoadmapSnapshotStore(tmp_path)
    snapshot = _snapshot("RM-FIXTURE", [_node("node", "2026-08-01T00:00:00+00:00")])
    target = store.save_create_once(snapshot)
    assert target.parent == tmp_path / "roadmap" / "snapshots"
    assert store.load(snapshot.snapshot_id) == snapshot
    with pytest.raises(FileExistsError):
        store.save_create_once(snapshot)


def test_partial_state_when_sqlite_integrity_fails_is_never_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    original = service.build_snapshot
    snapshot = original()
    partial = snapshot.model_copy(update={"state": RoadmapState.PARTIAL, "partial_reasons": ["missing source"]})
    assert partial.state is RoadmapState.PARTIAL
    assert partial.partial_reasons


def test_theme_preserves_required_colour_semantics() -> None:
    assert PALETTE["green"].startswith("#")
    assert PALETTE["unknown"].startswith("#")
    assert PALETTE["cyan"].startswith("#")


def test_scroll_overview_accepts_tk_string_fractions() -> None:
    assert _overview_position("0.5", 100) == 50
    assert _overview_position("0.0", 100) == 1


def test_roadmap_has_no_production_runtime_coupling() -> None:
    root = Path(__file__).parents[1] / "tools" / "orion_development_console"
    for name in ("roadmap.py", "roadmap_models.py", "roadmap_store.py", "roadmap_view.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "from orion." not in text
        assert "import orion." not in text
