from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.orion_arch_guard.fingerprints import canonical_sha256
from tools.orion_arch_guard.privacy import bounded_preview
from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.memory import DevelopmentMemoryService
from tools.orion_development_console.memory_models import DevelopmentCheckpoint, PromptRecord
from tools.orion_development_console.roadmap_models import (
    BranchType,
    DevelopmentPosition,
    MissingNode,
    NodeType,
    ProofBadge,
    ProvenancePointer,
    RoadmapDifferential,
    RoadmapEdge,
    RoadmapNode,
    RoadmapSnapshot,
    RoadmapState,
    RoadmapStatistics,
)
from tools.orion_development_console.roadmap_store import RoadmapSnapshotStore


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TEST = re.compile(r"(?i)\b(test|probe|experiment|evidence|smoke|validate|verification)\b")
_FIELD = re.compile(r"(?i)\b(field|flight|acoustic|human)\b")
_FAILURE = re.compile(r"(?i)\b(fail(?:ed|ure)?|broken|regression|defect)\b")
_ROOT_CAUSE = re.compile(r"(?i)\b(root.?cause|forensic|investigat|diagnos)\w*")
_FIX = re.compile(r"(?i)\b(fix|repair|correct|resolve|harden)\w*")
_RETEST = re.compile(r"(?i)\b(retest|re-test|prove again)\b")
_REFACTOR = re.compile(r"(?i)\b(refactor|rearchitect|separate|extract|migrat)\w*")
_REMOVE = re.compile(r"(?i)\b(remove|delete|retire|disconnect)\w*")
_SECRETISH = re.compile(r"(?i)(authorization|api[_-]?key|password|secret|token)\s*[:=]")

_SOURCE_TYPES = (
    "git_commit",
    "evidence_archive",
    "document_section",
    "chatgpt_conversation",
    "codex_session_meta",
    "release_tree_metadata",
)

_DURABLE_DOCUMENTS = (
    "docs/orion-master-decision-register-2026-09-01.md",
    "docs/orion-master-architecture-checkpoint-2026-09-01.md",
    "docs/ORION_PROJECT_MEMORY.md",
    "docs/orion-development-history-2026-09-02.md",
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _safe_text(value: object, *, fallback: str = "Untitled history item") -> str:
    preview = bounded_preview(value, limit=240) or fallback
    return _SECRETISH.sub("[REDACTED_CREDENTIAL]=", preview)


def _iso_date(value: object, *, fallback: str = "1970-01-01T00:00:00+00:00") -> str:
    text = str(value or "")
    match = _DATE.search(text)
    if not match:
        return fallback
    if "T" in text and text.startswith(match.group(0)):
        return text.replace("Z", "+00:00")
    return f"{match.group(0)}T00:00:00+00:00"


def _proofs(status: str, *, node_type: NodeType) -> tuple[list[ProofBadge], bool]:
    upper = status.upper()
    badges: list[ProofBadge] = []
    for token, badge in (
        ("FIELD_PROVEN", ProofBadge.FIELD_PROVEN),
        ("AUTOMATED_PROVEN", ProofBadge.AUTOMATED_PROVEN),
        ("PROBE_PROVEN", ProofBadge.PROBE_PROVEN),
        ("PROBE_PASS", ProofBadge.PROBE_PROVEN),
        ("IMPLEMENTED", ProofBadge.IMPLEMENTED),
        ("TESTED", ProofBadge.TESTED),
        ("FAILED", ProofBadge.FAILED),
        ("BLOCK", ProofBadge.BLOCKED),
        ("DEFERRED", ProofBadge.DEFERRED),
        ("SUPERSEDED", ProofBadge.SUPERSEDED),
        ("REJECTED", ProofBadge.REJECTED),
        ("REMOVED", ProofBadge.REMOVED),
        ("EXPLICITLY_REMOVED", ProofBadge.REMOVED),
        ("DISCONNECTED", ProofBadge.DISCONNECTED),
    ):
        if token in upper and badge not in badges:
            badges.append(badge)
    completed = any(
        badge in badges
        for badge in (
            ProofBadge.FIELD_PROVEN,
            ProofBadge.AUTOMATED_PROVEN,
            ProofBadge.PROBE_PROVEN,
        )
    )
    if node_type in {NodeType.DECISION, NodeType.GUARD_EVENT}:
        completed = not any(token in upper for token in ("PARTIAL", "DEFERRED", "NOT_YET", "BLOCK"))
    if node_type in {NodeType.FAILURE, NodeType.ROOT_CAUSE, NodeType.REJECTION, NodeType.REMOVAL, NodeType.SUPERSESSION}:
        completed = True
    return badges, completed


def _git_type(title: str) -> NodeType:
    if _RETEST.search(title):
        return NodeType.RETEST
    if _ROOT_CAUSE.search(title):
        return NodeType.ROOT_CAUSE
    if _FAILURE.search(title):
        return NodeType.FAILURE
    if _FIX.search(title):
        return NodeType.FIX
    if _REMOVE.search(title):
        return NodeType.REMOVAL
    if _REFACTOR.search(title):
        return NodeType.REFACTOR
    if _TEST.search(title):
        return NodeType.FIELD_TEST if _FIELD.search(title) else NodeType.TEST
    return NodeType.IMPLEMENTATION


def _branch_for(node_type: NodeType, status: str = "") -> BranchType:
    if node_type in {
        NodeType.TEST,
        NodeType.PROBE,
        NodeType.FIELD_TEST,
        NodeType.FAILURE,
        NodeType.ROOT_CAUSE,
        NodeType.FIX,
        NodeType.RETEST,
    }:
        return BranchType.TEST_EXPERIMENT
    if node_type is NodeType.GUARD_EVENT:
        return BranchType.GOVERNANCE
    if node_type is NodeType.PLANNED:
        return BranchType.FUTURE
    if any(word in status.upper() for word in ("SUPERSEDED", "REJECTED", "REMOVED", "DISCONNECTED", "HISTORICAL_ONLY")):
        return BranchType.HISTORICAL_ALTERNATIVE
    return BranchType.MAIN


class RoadmapService:
    """Read-only derived presentation over existing Guard and Phase 2 state."""

    def __init__(
        self,
        context: VerificationContext,
        *,
        memory: DevelopmentMemoryService | None = None,
        snapshots: RoadmapSnapshotStore | None = None,
        now: Callable[[], datetime] = _now_utc,
        database_path: Path | None = None,
    ) -> None:
        self.context = context
        self.memory = memory or DevelopmentMemoryService(context)
        self.snapshots = snapshots or RoadmapSnapshotStore(context.console_root)
        self.now = now
        self.database_path = database_path or context.guard_root / "index.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise FileNotFoundError(f"Architecture Guard index missing: {self.database_path}")
        connection = sqlite3.connect(
            f"file:{self.database_path.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _latest_guard(self) -> dict[str, Any]:
        reports = sorted(
            (self.context.guard_root / "reports").glob("AG-*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if not reports:
            raise FileNotFoundError("No Architecture Guard report is available")
        value = json.loads(reports[0].read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}

    def latest_guard_report(self) -> dict[str, Any]:
        return self._latest_guard()

    def canonical_summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_kind, COUNT(*) AS count FROM canonical_records GROUP BY record_kind"
            ).fetchall()
            records = [dict(row) for row in connection.execute(
                "SELECT record_id, record_kind, title, status, classification, priority, "
                "user_valued, summary FROM canonical_records ORDER BY record_kind, record_id"
            )]
            signature = connection.execute(
                "SELECT value FROM graph_metadata WHERE key='CANONICAL_INPUT_SIGNATURE'"
            ).fetchone()
        counts = {str(row["record_kind"]): int(row["count"]) for row in rows}
        return {
            "strategy": "STRATEGY_A_CURRENT_RECONNECT",
            "current_position": "CANONICAL ORION BASELINE ESTABLISHED",
            "next_step": "REALTIME INFORMATIONAL PRESENTER RELIABILITY CORRECTION",
            "counts": counts,
            "records": records,
            "input_signature": str(signature[0]) if signature else "MISSING",
        }

    def dependency_fingerprint(self) -> tuple[str, dict[str, str | None]]:
        git = self.memory.current_git()
        guard = self._latest_guard()
        checkpoint = self.memory.latest_checkpoint()
        with self._connect() as connection:
            graph = connection.execute(
                "SELECT value FROM graph_metadata WHERE key = 'AG2_INPUT_SIGNATURE'"
            ).fetchone()
            evidence = connection.execute(
                "SELECT item_id, timestamp_utc FROM source_items WHERE item_type = 'evidence_archive' ORDER BY timestamp_utc DESC, item_id DESC LIMIT 1"
            ).fetchone()
            snapshot = connection.execute(
                "SELECT snapshot_id, manifest_sha256 FROM source_snapshots ORDER BY indexed_at_utc DESC LIMIT 1"
            ).fetchone()
        details: dict[str, str | None] = {
            "head": str(git.get("head") or "UNKNOWN"),
            "guard_report_id": str(guard.get("report_id") or "UNKNOWN"),
            "guard_gate": str(guard.get("gate") or "UNKNOWN"),
            "graph_signature": str(graph[0]) if graph else "UNKNOWN",
            "checkpoint_id": checkpoint.checkpoint_id if checkpoint else None,
            "checkpoint_fingerprint": checkpoint.content_fingerprint if checkpoint else None,
            "evidence_id": str(evidence[0]) if evidence else None,
            "evidence_timestamp": str(evidence[1]) if evidence else None,
            "source_snapshot_id": str(snapshot[0]) if snapshot else None,
            "source_manifest": str(snapshot[1]) if snapshot else None,
        }
        for relative in _DURABLE_DOCUMENTS:
            path = self.context.repository_root / relative
            details[f"document:{relative}"] = (
                canonical_sha256(path.read_text(encoding="utf-8")).casefold()
                if path.is_file()
                else None
            )
        return canonical_sha256(details).casefold(), details

    def freshness(self, snapshot: RoadmapSnapshot | None = None) -> RoadmapState:
        current = snapshot or self.snapshots.latest()
        if current is None:
            return RoadmapState.REFRESH_REQUIRED
        fingerprint, _details = self.dependency_fingerprint()
        if current.state is RoadmapState.ERROR:
            return RoadmapState.ERROR
        if current.dependency_fingerprint != fingerprint:
            return RoadmapState.STALE
        return current.state

    def refresh(self, *, persist: bool = True) -> tuple[RoadmapSnapshot, RoadmapDifferential]:
        previous = self.snapshots.latest()
        snapshot = self.build_snapshot()
        differential = compare_snapshots(previous, snapshot)
        if persist:
            self.snapshots.save_create_once(snapshot)
        return snapshot, differential

    def development_position(
        self, snapshot: RoadmapSnapshot | None = None
    ) -> DevelopmentPosition:
        current_snapshot = snapshot or self.build_snapshot()
        current = next(
            node
            for node in current_snapshot.nodes
            if node.node_id == current_snapshot.current_node_id
        )
        approved_next = next(
            (
                node
                for node in current_snapshot.nodes
                if node.status == "APPROVED_NEXT_STEP"
            ),
            None,
        )
        provenance = [*current.provenance]
        if approved_next:
            provenance.extend(approved_next.provenance)
        return DevelopmentPosition(
            development_stage=current.title,
            development_status=current.status,
            approved_next_step=approved_next.title if approved_next else None,
            current_node_id=current.node_id,
            approved_next_node_id=approved_next.node_id if approved_next else None,
            derived_from_snapshot_id=current_snapshot.snapshot_id,
            provenance=provenance,
        )

    def checkpoint_candidate(
        self, snapshot: RoadmapSnapshot | None = None
    ) -> DevelopmentCheckpoint:
        position = self.development_position(snapshot)
        return self.memory.build_checkpoint_candidate(
            development_stage=position.checkpoint_stage,
            approved_next_step=position.approved_next_step,
            known_problems=[
                "Direct ChatGPT/Codex send has no approved Console integration contract"
            ],
            risks=[]
            if position.approved_next_step
            else ["Approved Next Step is not recorded; Continue remains blocked"],
        )

    def build_snapshot(self) -> RoadmapSnapshot:
        started = time.perf_counter()
        dependency, dependencies = self.dependency_fingerprint()
        nodes: list[RoadmapNode] = []
        edges: list[RoadmapEdge] = []
        partial: list[str] = []
        guard = self._latest_guard()
        with self._connect() as connection:
            quick = connection.execute("PRAGMA quick_check").fetchone()
            if not quick or str(quick[0]).casefold() != "ok":
                partial.append("Architecture Guard SQLite quick_check did not return ok")
            nodes.extend(self._source_nodes(connection))
            graph_nodes, graph_edges = self._graph_nodes(connection)
            nodes.extend(graph_nodes)
            edges.extend(graph_edges)
            guard_nodes = self._guard_nodes(connection)
            nodes.extend(guard_nodes)
            nodes.extend(self._canonical_nodes(connection, str(guard.get("report_id") or "UNKNOWN")))
        nodes.extend(self._live_document_nodes())
        checkpoint_nodes = self._checkpoint_nodes()
        nodes.extend(checkpoint_nodes)
        nodes = self._deduplicate_nodes(nodes)
        stage_nodes, stage_edges = self._stage_nodes(nodes)
        nodes.extend(stage_nodes)
        edges.extend(stage_edges)
        edges.extend(self._parent_edges(nodes))
        nodes.sort(key=_node_sort_key)
        edges = self._deduplicate_edges(edges)
        current = next((node for node in nodes if node.current), nodes[-1])
        state = RoadmapState.PARTIAL if partial else RoadmapState.CURRENT
        statistics = roadmap_statistics(nodes, edges)
        generated_at = self.now().astimezone(UTC).isoformat()
        snapshot_id = f"RM-{self.now().astimezone(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        snapshot = RoadmapSnapshot(
            snapshot_id=snapshot_id,
            generated_at=generated_at,
            state=state,
            dependency_fingerprint=dependency,
            content_fingerprint="",
            repository_head=str(dependencies["head"]),
            guard_report_id=str(dependencies["guard_report_id"]),
            guard_graph_signature=str(dependencies["graph_signature"]),
            latest_checkpoint_id=dependencies["checkpoint_id"],
            latest_evidence_id=dependencies["evidence_id"],
            current_node_id=current.node_id,
            nodes=nodes,
            edges=edges,
            statistics=statistics,
            partial_reasons=partial,
            build_duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return snapshot.model_copy(
            update={"content_fingerprint": snapshot.expected_fingerprint()}
        )

    def _source_nodes(self, connection: sqlite3.Connection) -> list[RoadmapNode]:
        placeholders = ",".join("?" for _ in _SOURCE_TYPES)
        rows = connection.execute(
            f"SELECT item_id, item_type, timestamp_utc, bounded_preview, metadata_json, source_pointer_json FROM source_items WHERE item_type IN ({placeholders}) ORDER BY timestamp_utc, item_id",
            _SOURCE_TYPES,
        )
        nodes: list[RoadmapNode] = []
        for row in rows:
            item_type = str(row["item_type"])
            title = _safe_text(row["bounded_preview"], fallback=str(row["item_id"]))
            metadata = _json(row["metadata_json"], {})
            pointer = _json(row["source_pointer_json"], {})
            occurred_at = _iso_date(row["timestamp_utc"])
            node_type = NodeType.MILESTONE
            status = "RECOVERED_HISTORY"
            badges: list[ProofBadge] = []
            completed = True
            branch = BranchType.MAIN
            commits: list[str] = []
            evidence: list[str] = []
            parent_ids: list[str] = []
            category = "HISTORY"
            if item_type == "git_commit":
                node_type = _git_type(title)
                status = "COMMITTED"
                commits = [str(metadata.get("commit_sha") or pointer.get("commit_sha") or row["item_id"]).removeprefix("git:commit:")]
                parent_ids = [f"git:commit:{value}" for value in metadata.get("parents", [])]
                category = "GIT"
                branch = _branch_for(node_type)
                if node_type in {NodeType.TEST, NodeType.RETEST}:
                    badges = [ProofBadge.TESTED, ProofBadge.AUTOMATED_PROVEN]
                    completed = True
                elif node_type is NodeType.FIELD_TEST:
                    badges = [ProofBadge.TESTED]
                    completed = False
                elif node_type is NodeType.FAILURE:
                    badges = [ProofBadge.FAILED]
                    completed = True
                elif node_type is NodeType.REMOVAL:
                    badges = [ProofBadge.REMOVED]
                    completed = True
                else:
                    badges = [ProofBadge.IMPLEMENTED]
                    completed = False
            elif item_type == "evidence_archive":
                node_type = NodeType.FIELD_TEST
                status = "EVIDENCE_RECORDED"
                evidence = [str(row["item_id"])]
                category = "EVIDENCE"
                branch = BranchType.TEST_EXPERIMENT
                badges = [ProofBadge.TESTED]
                completed = False
                title = f"Evidence archive · {str(row['item_id'])[-12:]}"
            elif item_type == "document_section":
                category = "DECISION"
                status = "DURABLE_HISTORY"
            elif item_type == "chatgpt_conversation":
                category = "CHAT"
                status = "RECOVERED_L0_SUMMARY"
            elif item_type == "codex_session_meta":
                category = "CODEX"
                status = "RECOVERED_L0_SUMMARY"
            elif item_type == "release_tree_metadata":
                category = "EVIDENCE"
                status = "RELEASE_SNAPSHOT"
            nodes.append(
                RoadmapNode(
                    node_id=str(row["item_id"]),
                    node_type=node_type,
                    title=title,
                    description=f"Derived from existing {item_type.replace('_', ' ')} metadata.",
                    occurred_at=occurred_at,
                    branch_type=branch,
                    status=status,
                    proof_badges=badges,
                    completed=completed,
                    commit_shas=commits,
                    evidence_ids=evidence,
                    parent_ids=parent_ids,
                    provider=str(metadata.get("provider")) if metadata.get("provider") else None,
                    provenance=[
                        ProvenancePointer(
                            category=category,
                            source_item_id=str(row["item_id"]),
                            pointer=pointer if isinstance(pointer, dict) else {},
                            confidence="VERY_HIGH",
                        )
                    ],
                    metadata=metadata if isinstance(metadata, dict) else {},
                )
            )
        return nodes

    def _canonical_nodes(
        self, connection: sqlite3.Connection, guard_report_id: str
    ) -> list[RoadmapNode]:
        nodes: list[RoadmapNode] = []
        rows = connection.execute(
            "SELECT * FROM canonical_records ORDER BY record_kind, record_id"
        ).fetchall()
        for index, row in enumerate(rows):
            kind = str(row["record_kind"])
            status = str(row["status"])
            metadata = _json(row["metadata_json"], {})
            capabilities = list(_json(row["capabilities_json"], []))
            evidence = list(_json(row["evidence_refs_json"], []))
            if kind in {"RECOVERED_IDEA", "USER_VALUED_FORGOTTEN_IDEA"}:
                node_type = NodeType.RECOVERED_IDEA
                branch = BranchType.RECOVERED_FUTURE
                badges = [ProofBadge.RECOVERED]
                completed = False
            elif kind == "HISTORICAL_RECONNECT_ITEM":
                node_type = NodeType.HISTORICAL_RECONNECT
                branch = BranchType.HISTORICAL_ALTERNATIVE
                badges = [ProofBadge.PROBE_PROVEN]
                completed = False
            elif kind == "RETIREMENT_CANDIDATE":
                node_type = NodeType.RETIREMENT
                branch = BranchType.HISTORICAL_ALTERNATIVE
                badges = [ProofBadge.SUPERSEDED]
                completed = True
            elif kind == "CANONICAL_ROADMAP_STAGE":
                node_type = NodeType.MILESTONE if status in {"COMPLETE", "CURRENT"} else NodeType.PLANNED
                branch = BranchType.GOVERNANCE if status in {"COMPLETE", "CURRENT"} else BranchType.FUTURE
                badges = [ProofBadge.AUTOMATED_PROVEN] if status in {"COMPLETE", "CURRENT"} else []
                completed = status in {"COMPLETE", "CURRENT"}
            else:
                node_type = NodeType.CANONICAL
                branch = BranchType.MAIN if kind == "GOLDEN_COMPONENT" else BranchType.GOVERNANCE
                badges = [ProofBadge.AUTOMATED_PROVEN] if kind == "GOLDEN_COMPONENT" else [ProofBadge.IMPLEMENTED]
                completed = True
            record_id = str(row["record_id"])
            nodes.append(
                RoadmapNode(
                    node_id=f"canonical:{record_id}",
                    node_type=node_type,
                    title=str(row["title"]),
                    description=str(row["summary"]),
                    occurred_at=f"2026-09-03T{index // 60:02d}:{index % 60:02d}:00+00:00",
                    branch_type=branch,
                    status=status,
                    proof_badges=badges,
                    completed=completed,
                    current=status == "CURRENT" or bool(metadata.get("current_position")),
                    capabilities=capabilities,
                    decision_ids=["D74"],
                    evidence_ids=evidence,
                    guard_report_ids=[guard_report_id],
                    parent_ids=["canonical:C0"] if record_id == "C1" else [],
                    provenance=[
                        ProvenancePointer(
                            category="GUARD",
                            source_item_id="D74",
                            pointer={
                                "record_id": record_id,
                                "record_kind": kind,
                                "input_signature": row["input_signature"],
                            },
                            confidence="VERY_HIGH",
                        )
                    ],
                    metadata={
                        "canonical_kind": kind,
                        "classification": row["classification"],
                        "priority": row["priority"],
                        "user_decision_required": bool(row["user_decision_required"]),
                        "user_valued": bool(row["user_valued"]),
                        "proof_level": row["proof_level"],
                        "recommended_action": row["recommended_action"],
                        "source_refs": _json(row["source_refs_json"], []),
                        **metadata,
                    },
                )
            )
        return nodes

    def _live_document_nodes(self) -> list[RoadmapNode]:
        nodes: list[RoadmapNode] = []
        for relative in _DURABLE_DOCUMENTS:
            path = self.context.repository_root / relative
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            content_sha = canonical_sha256(text).casefold()
            ordinal_by_heading: dict[str, int] = defaultdict(int)
            for line_number, line in enumerate(text.splitlines(), start=1):
                if not line.startswith("#"):
                    continue
                heading = line.lstrip("#").strip()
                if not heading:
                    continue
                key = heading.casefold()
                ordinal_by_heading[key] += 1
                identity = canonical_sha256(
                    [relative.casefold(), key, ordinal_by_heading[key]]
                )[:24].casefold()
                occurred = _iso_date(
                    heading,
                    fallback=_iso_date(Path(relative).stem, fallback="2026-09-02T00:00:00+00:00"),
                )
                nodes.append(
                    RoadmapNode(
                        node_id=f"live-document:{identity}",
                        node_type=NodeType.MILESTONE,
                        title=f"{Path(relative).name} · {_safe_text(heading)}",
                        description="Current durable document heading, read directly during Roadmap refresh.",
                        occurred_at=occurred,
                        status="DURABLE_HISTORY",
                        completed=True,
                        provenance=[
                            ProvenancePointer(
                                category="DECISION",
                                source_item_id=f"document:{relative}:{identity}",
                                pointer={
                                    "path": relative,
                                    "line_start": line_number,
                                    "content_sha256": content_sha,
                                },
                                confidence="VERY_HIGH",
                            )
                        ],
                    )
                )
        return nodes

    def _graph_nodes(
        self, connection: sqlite3.Connection
    ) -> tuple[list[RoadmapNode], list[RoadmapEdge]]:
        nodes: list[RoadmapNode] = []
        edges: list[RoadmapEdge] = []
        provenance_rows: dict[tuple[str, str], list[ProvenancePointer]] = defaultdict(list)
        for row in connection.execute(
            "SELECT node_type, node_id, source_item_id, source_pointer_json, confidence FROM graph_provenance"
        ):
            provenance_rows[(str(row["node_type"]), str(row["node_id"]))].append(
                ProvenancePointer(
                    category=_provenance_category(row["source_item_id"]),
                    source_item_id=str(row["source_item_id"]) if row["source_item_id"] else None,
                    pointer=_json(row["source_pointer_json"], {}),
                    confidence=str(row["confidence"]),
                )
            )
        node_ids: dict[tuple[str, str], str] = {}
        last_decision_date = "2026-08-01T00:00:00+00:00"
        for row in connection.execute("SELECT * FROM decisions ORDER BY decision_id"):
            status = str(row["decision_status"])
            badges, completed = _proofs(status, node_type=NodeType.DECISION)
            decision_id = str(row["decision_id"])
            metadata = _json(row["metadata_json"], {})
            node_id = f"decision:{decision_id}"
            node_ids[("DECISION", decision_id)] = node_id
            decision_date = _iso_date(row["decision_date"], fallback=last_decision_date)
            last_decision_date = decision_date
            nodes.append(
                RoadmapNode(
                    node_id=node_id,
                    node_type=_decision_node_type(status),
                    title=f"{decision_id} · {_safe_text(row['decision_text'])}",
                    description=_safe_text(row["evidence_summary"], fallback="Decision Register entry"),
                    occurred_at=decision_date,
                    branch_type=_branch_for(NodeType.DECISION, status),
                    status=status,
                    proof_badges=badges,
                    completed=completed,
                    capabilities=list(metadata.get("capabilities", [])),
                    decision_ids=[decision_id],
                    provenance=provenance_rows[("DECISION", decision_id)],
                    metadata={
                        "area": row["area"],
                        "proposed_by": row["proposed_by"],
                        "user_approval": row["user_approval"],
                        "historical_implementation": row["historical_implementation"],
                        "current_implementation": row["current_implementation"],
                        **metadata,
                    },
                )
            )
        implementations: list[dict[str, Any]] = []
        for row in connection.execute("SELECT * FROM implementations ORDER BY implementation_id"):
            implementation_id = str(row["implementation_id"])
            status = f"{row['runtime_status']} / {row['historical_status']}"
            metadata = _json(row["metadata_json"], {})
            badges, completed = _proofs(status, node_type=NodeType.IMPLEMENTATION)
            node_type = _implementation_node_type(status)
            node_id = f"implementation:{implementation_id}"
            node_ids[("IMPLEMENTATION", implementation_id)] = node_id
            commits = list(_json(row["commit_range_json"], []))
            implementation = {
                "id": implementation_id,
                "date": _iso_date(row["introduced_at"]),
                "capabilities": list(metadata.get("capabilities", [])),
                "defects": list(_json(row["defects_json"], [])),
                "evidence": list(metadata.get("evidence", [])),
                "title": str(row["name"]),
                "node_id": node_id,
                "provenance": provenance_rows[("IMPLEMENTATION", implementation_id)],
            }
            implementations.append(implementation)
            nodes.append(
                RoadmapNode(
                    node_id=node_id,
                    node_type=node_type,
                    title=_safe_text(row["name"], fallback=implementation_id),
                    description=_safe_text(
                        "; ".join(_json(row["strengths_json"], [])),
                        fallback="Guard implementation record",
                    ),
                    occurred_at=implementation["date"],
                    branch_type=_branch_for(node_type, status),
                    status=status,
                    proof_badges=badges,
                    completed=completed,
                    capabilities=implementation["capabilities"],
                    commit_shas=commits,
                    evidence_ids=implementation["evidence"],
                    provider=str(row["provider"]) if row["provider"] else None,
                    session_model=str(row["session_model"]) if row["session_model"] else None,
                    provenance=implementation["provenance"],
                    metadata={
                        "graph_kind": "IMPLEMENTATION",
                        "files_components": _json(row["files_components_json"], []),
                        "strengths": _json(row["strengths_json"], []),
                        "defects": implementation["defects"],
                        "abandonment_reason": row["abandonment_reason"],
                        **metadata,
                    },
                )
            )
        for row in connection.execute("SELECT * FROM mechanisms ORDER BY mechanism_id"):
            mechanism_id = str(row["mechanism_id"])
            status = f"{row['historical_status']} / {row['field_probe_status']}"
            badges, completed = _proofs(status, node_type=NodeType.IMPLEMENTATION)
            node_id = f"mechanism:{mechanism_id}"
            node_ids[("MECHANISM", mechanism_id)] = node_id
            metadata = _json(row["metadata_json"], {})
            nodes.append(
                RoadmapNode(
                    node_id=node_id,
                    node_type=_implementation_node_type(status),
                    title=f"Mechanism · {_safe_text(row['name'], fallback=mechanism_id)}",
                    description=_safe_text(row["description"], fallback=str(row["invariant_text"])),
                    occurred_at=_provenance_date(provenance_rows[("MECHANISM", mechanism_id)]),
                    branch_type=_branch_for(NodeType.IMPLEMENTATION, status),
                    status=status,
                    proof_badges=badges,
                    completed=completed,
                    capabilities=list(metadata.get("capabilities", [])),
                    provenance=provenance_rows[("MECHANISM", mechanism_id)],
                    metadata={"graph_kind": "MECHANISM", "invariant": row["invariant_text"], **metadata},
                )
            )
        for row in connection.execute("SELECT * FROM evidence ORDER BY evidence_id"):
            evidence_id = str(row["evidence_id"])
            status = str(row["evidence_status"])
            badges, completed = _proofs(status, node_type=NodeType.FIELD_TEST)
            node_id = f"graph-evidence:{evidence_id}"
            node_ids[("EVIDENCE", evidence_id)] = node_id
            nodes.append(
                RoadmapNode(
                    node_id=node_id,
                    node_type=NodeType.FIELD_TEST,
                    title=f"Evidence · {_safe_text(row['name'], fallback=evidence_id)}",
                    description=f"Guard evidence type: {row['evidence_type']}",
                    occurred_at=_provenance_date(provenance_rows[("EVIDENCE", evidence_id)]),
                    branch_type=BranchType.TEST_EXPERIMENT,
                    status=status,
                    proof_badges=badges or [ProofBadge.TESTED],
                    completed=completed,
                    evidence_ids=[evidence_id],
                    provenance=provenance_rows[("EVIDENCE", evidence_id)],
                    metadata=_json(row["metadata_json"], {}),
                )
            )
        defect_nodes, defect_edges = _derive_defect_chains(implementations)
        nodes.extend(defect_nodes)
        edges.extend(defect_edges)
        for row in connection.execute("SELECT * FROM capabilities ORDER BY capability_id"):
            capability_id = str(row["capability_id"])
            node_id = f"capability:{capability_id}"
            node_ids[("CAPABILITY", capability_id)] = node_id
            nodes.append(
                RoadmapNode(
                    node_id=node_id,
                    node_type=NodeType.SUBSYSTEM,
                    title=f"Subsystem · {capability_id}",
                    description=_safe_text(row["description"], fallback="Guard capability taxonomy"),
                    occurred_at="2026-08-01T00:00:00+00:00",
                    status="DERIVED_TAXONOMY",
                    completed=True,
                    capabilities=[capability_id],
                    subsystem=capability_id,
                    provenance=[ProvenancePointer(category="GUARD", pointer={"graph_node": capability_id})],
                    metadata=_json(row["metadata_json"], {}),
                )
            )
        for row in connection.execute("SELECT * FROM relationships ORDER BY relationship_id"):
            source = node_ids.get((str(row["source_node_type"]), str(row["source_node_id"])))
            target = node_ids.get((str(row["target_node_type"]), str(row["target_node_id"])))
            if not source or not target:
                continue
            relationship = str(row["relationship_type"])
            edges.append(
                RoadmapEdge(
                    edge_id=f"graph:{row['relationship_id']}",
                    source_id=source,
                    target_id=target,
                    relationship=relationship,
                    branch_type=(
                        BranchType.HISTORICAL_ALTERNATIVE
                        if relationship in {"SUPERSEDES", "REPLACED_BY", "REJECTS"}
                        else BranchType.MAIN
                    ),
                    provenance=[
                        ProvenancePointer(
                            category="GUARD",
                            pointer=_json(row["provenance_json"], {}),
                            confidence=str(row["confidence"]),
                        )
                    ],
                )
            )
        return nodes, edges

    def _guard_nodes(self, connection: sqlite3.Connection) -> list[RoadmapNode]:
        nodes: list[RoadmapNode] = []
        for row in connection.execute("SELECT * FROM guard_runs ORDER BY created_at_utc, run_id"):
            gate = str(row["gate"])
            badges, completed = _proofs(gate, node_type=NodeType.GUARD_EVENT)
            input_value = _json(row["input_json"], {})
            nodes.append(
                RoadmapNode(
                    node_id=f"guard:{row['run_id']}",
                    node_type=NodeType.GUARD_EVENT,
                    title=f"{row['run_id']} · {gate}",
                    description=_safe_text(input_value.get("task_title"), fallback="Architecture Guard run"),
                    occurred_at=_iso_date(row["created_at_utc"]),
                    branch_type=BranchType.GOVERNANCE,
                    status=gate,
                    proof_badges=badges,
                    completed=completed,
                    guard_report_ids=[str(row["run_id"])],
                    commit_shas=[str(row["head_sha"])] if row["head_sha"] else [],
                    provenance=[
                        ProvenancePointer(
                            category="GUARD",
                            pointer={"run_id": row["run_id"], "json_report_path": row["json_report_path"]},
                            confidence="VERY_HIGH",
                        )
                    ],
                    metadata={"mode": row["mode_effective"], "ruleset_version": row["ruleset_version"]},
                )
            )
        return nodes

    def _checkpoint_nodes(self) -> list[RoadmapNode]:
        nodes: list[RoadmapNode] = []
        for checkpoint in self.memory.checkpoints.list_records():
            nodes.append(
                RoadmapNode(
                    node_id=f"checkpoint:{checkpoint.checkpoint_id}",
                    node_type=NodeType.CHECKPOINT,
                    title=f"Checkpoint · {checkpoint.development_stage}",
                    description=f"Approved next step: {checkpoint.approved_next_step or 'NOT RECORDED'}",
                    occurred_at=_iso_date(checkpoint.created_at),
                    status="SAVED_IMMUTABLE",
                    proof_badges=[ProofBadge.IMPLEMENTED],
                    completed=True,
                    decision_ids=checkpoint.current_decisions,
                    commit_shas=[checkpoint.head_sha],
                    guard_report_ids=[checkpoint.guard_report_id],
                    verification_report_ids=[checkpoint.verification_report_id] if checkpoint.verification_report_id else [],
                    checkpoint_ids=[checkpoint.checkpoint_id],
                    provenance=[
                        ProvenancePointer(
                            category="CHECKPOINT",
                            source_item_id=checkpoint.checkpoint_id,
                            pointer={"content_fingerprint": checkpoint.content_fingerprint},
                            confidence="VERY_HIGH",
                        )
                    ],
                )
            )
        return nodes

    def _phase_and_future_nodes(
        self, existing: Sequence[RoadmapNode], guard_report_id: str
    ) -> list[RoadmapNode]:
        history_path = self.context.repository_root / "docs" / "orion-development-history-2026-09-02.md"
        history = history_path.read_text(encoding="utf-8") if history_path.is_file() else ""
        phase3_complete = "Development Console Phase 3" in history
        latest_time = max((_node_sort_key(node)[0] for node in existing), default="2026-09-02T00:00:00+00:00")
        phase3 = RoadmapNode(
            node_id="milestone:development-console-phase3",
            node_type=NodeType.MILESTONE,
            title="Development Console Phase 3 · Live Roadmap",
            description="Derived maximum-detail graphical navigation over existing ORION history.",
            occurred_at=latest_time,
            status="FIELD_PROVEN" if phase3_complete else "IN_PROGRESS",
            proof_badges=[ProofBadge.FIELD_PROVEN] if phase3_complete else [ProofBadge.IMPLEMENTED],
            completed=phase3_complete,
            current=not phase3_complete,
            guard_report_ids=[guard_report_id],
            provenance=[ProvenancePointer(category="GUARD", pointer={"report_id": guard_report_id})],
        )
        checkpoint = RoadmapNode(
            node_id="planned:full-development-console-checkpoint",
            node_type=NodeType.PLANNED,
            title="Full Development Console checkpoint",
            description="Explicit user SAVE is required by the Phase 2 checkpoint contract.",
            occurred_at="2026-09-03T00:00:00+00:00",
            branch_type=BranchType.FUTURE,
            status="READY_FOR_USER_SAVE" if phase3_complete else "APPROVED_FUTURE",
            completed=False,
            current=phase3_complete,
            parent_ids=[phase3.node_id],
            provenance=[ProvenancePointer(category="DECISION", pointer={"approved_phase": "Phase 3 task"})],
        )
        latency = RoadmapNode(
            node_id="planned:low-latency-natural-informational-presentation",
            node_type=NodeType.PLANNED,
            title="Low-latency natural informational presentation",
            description="Run a new FULL Architecture Guard preflight before implementation.",
            occurred_at="2026-09-03T00:00:01+00:00",
            branch_type=BranchType.FUTURE,
            status="APPROVED_NEXT_STEP",
            completed=False,
            parent_ids=[checkpoint.node_id],
            capabilities=["NATURAL_INFORMATIONAL_PRESENTATION"],
            provenance=[ProvenancePointer(category="DECISION", pointer={"approved_phase": "Phase 3 task"})],
        )
        return [phase3, checkpoint, latency]

    @staticmethod
    def _deduplicate_nodes(nodes: Iterable[RoadmapNode]) -> list[RoadmapNode]:
        result: dict[str, RoadmapNode] = {}
        for node in nodes:
            result[node.node_id] = node
        return list(result.values())

    @staticmethod
    def _deduplicate_edges(edges: Iterable[RoadmapEdge]) -> list[RoadmapEdge]:
        result: dict[str, RoadmapEdge] = {}
        for edge in edges:
            if edge.source_id != edge.target_id:
                result[edge.edge_id] = edge
        return sorted(result.values(), key=lambda edge: edge.edge_id)

    @staticmethod
    def _parent_edges(nodes: Sequence[RoadmapNode]) -> list[RoadmapEdge]:
        known = {node.node_id for node in nodes}
        edges = []
        for node in nodes:
            for parent in node.parent_ids:
                if parent in known:
                    edges.append(
                        RoadmapEdge(
                            edge_id="parent:" + canonical_sha256([parent, node.node_id])[:24].casefold(),
                            source_id=parent,
                            target_id=node.node_id,
                            relationship="PRECEDES_OR_PARENTS",
                            branch_type=node.branch_type,
                        )
                    )
        return edges

    @staticmethod
    def _stage_nodes(
        nodes: Sequence[RoadmapNode],
    ) -> tuple[list[RoadmapNode], list[RoadmapEdge]]:
        grouped: dict[str, list[RoadmapNode]] = defaultdict(list)
        for node in nodes:
            if node.node_type not in {NodeType.PROJECT, NodeType.STAGE, NodeType.SUBSYSTEM, NodeType.PLANNED}:
                grouped[node.occurred_at[:10]].append(node)
        stages: list[RoadmapNode] = [
            RoadmapNode(
                node_id="project:orion",
                node_type=NodeType.PROJECT,
                title="ORION · Complete recovered development history",
                description="Oldest available bounded history to current development and approved future work.",
                occurred_at="2026-08-01T00:00:00+00:00",
                status="ACTIVE",
                completed=False,
                provenance=[ProvenancePointer(category="GUARD", pointer={"derivation": "AG-0/1/2/3"})],
            )
        ]
        edges: list[RoadmapEdge] = []
        previous = "project:orion"
        for day, children in sorted(grouped.items()):
            stage_id = f"stage:{day}"
            stages.append(
                RoadmapNode(
                    node_id=stage_id,
                    node_type=NodeType.STAGE,
                    title=f"Development stage - {day}",
                    description=f"{len(children)} derived historical events",
                    occurred_at=f"{day}T00:00:00+00:00",
                    status="DERIVED_GROUP",
                    completed=all(child.completed for child in children),
                    parent_ids=[previous],
                    provenance=[ProvenancePointer(category="GUARD", pointer={"derived_children": len(children)})],
                    metadata={
                        "decisions": sum(child.node_type is NodeType.DECISION for child in children),
                        "implementations": sum(child.node_type is NodeType.IMPLEMENTATION for child in children),
                        "tests": sum(child.node_type in {NodeType.TEST, NodeType.PROBE, NodeType.FIELD_TEST, NodeType.RETEST} for child in children),
                        "failures": sum(child.node_type in {NodeType.FAILURE, NodeType.ROOT_CAUSE, NodeType.FIX} for child in children),
                        "checkpoints": sum(child.node_type is NodeType.CHECKPOINT for child in children),
                    },
                )
            )
            edges.append(
                RoadmapEdge(
                    edge_id=f"stage-chain:{day}",
                    source_id=previous,
                    target_id=stage_id,
                    relationship="CHRONOLOGICAL_STAGE",
                )
            )
            for child in children:
                edges.append(
                    RoadmapEdge(
                        edge_id="stage-member:" + canonical_sha256([stage_id, child.node_id])[:24].casefold(),
                        source_id=stage_id,
                        target_id=child.node_id,
                        relationship="CONTAINS_EVENT",
                        branch_type=child.branch_type,
                    )
                )
            previous = stage_id
        return stages, edges

    def search(self, snapshot: RoadmapSnapshot, query: str) -> list[RoadmapNode]:
        terms = [term.casefold() for term in query.split() if term]
        if not terms:
            return []
        matches: list[tuple[int, RoadmapNode]] = []
        for node in snapshot.nodes:
            identifiers = [
                node.node_id,
                *node.capabilities,
                *node.decision_ids,
                *node.commit_shas,
                *node.evidence_ids,
                *node.guard_report_ids,
                *node.verification_report_ids,
                *node.checkpoint_ids,
            ]
            visible = [
                *identifiers,
                node.title,
                node.description,
                node.status,
                node.provider or "",
                node.session_model or "",
                node.subsystem or "",
                json.dumps(node.metadata, ensure_ascii=False),
                *(str(item.pointer.get("path", "")) for item in node.provenance),
            ]
            payload = " ".join(visible).casefold()
            if all(term in payload for term in terms):
                exact = {value.casefold() for value in identifiers}
                score = sum(100 if term in exact else 20 if term in node.title.casefold() else 1 for term in terms)
                matches.append((score, node))
        return [node for _score, node in sorted(matches, key=lambda item: (-item[0], _node_sort_key(item[1])))]

    @staticmethod
    def filtered_nodes(
        snapshot: RoadmapSnapshot,
        filter_name: str,
        *,
        collapsed: set[str] | None = None,
    ) -> list[RoadmapNode]:
        collapsed_ids = collapsed or set()
        hidden = {
            edge.target_id
            for edge in snapshot.edges
            if edge.source_id in collapsed_ids and edge.relationship == "CONTAINS_EVENT"
        }
        name = filter_name.upper()
        result = []
        for node in snapshot.nodes:
            if node.node_id in hidden:
                continue
            if name == "ALL":
                include = True
            elif name == "MAIN DEVELOPMENT":
                include = node.branch_type is BranchType.MAIN
            elif name == "TEST / EXPERIMENT":
                include = node.branch_type is BranchType.TEST_EXPERIMENT
            elif name == "FIELD_PROVEN":
                include = ProofBadge.FIELD_PROVEN in node.proof_badges
            elif name == "FAILURES / FIXES":
                include = node.node_type in {NodeType.FAILURE, NodeType.ROOT_CAUSE, NodeType.FIX, NodeType.RETEST}
            elif name == "UNFINISHED":
                include = not node.completed
            elif name == "SUPERSEDED / REJECTED":
                include = any(badge in node.proof_badges for badge in (ProofBadge.SUPERSEDED, ProofBadge.REJECTED, ProofBadge.REMOVED, ProofBadge.DISCONNECTED))
            elif name == "DECISIONS":
                include = bool(node.decision_ids) or node.node_type in {NodeType.DECISION, NodeType.REJECTION, NodeType.SUPERSESSION}
            elif name == "CHECKPOINTS":
                include = node.node_type is NodeType.CHECKPOINT
            elif name == "HISTORICAL RECONNECT":
                include = node.node_type is NodeType.HISTORICAL_RECONNECT
            elif name == "RECOVERED IDEAS":
                include = node.metadata.get("canonical_kind") == "RECOVERED_IDEA"
            elif name == "CANONICAL":
                include = node.node_type in {NodeType.CANONICAL, NodeType.HISTORICAL_RECONNECT, NodeType.RECOVERED_IDEA, NodeType.RETIREMENT}
            else:
                include = True
            if include:
                result.append(node)
        return result

    def recall_node(self, snapshot: RoadmapSnapshot, node_id: str) -> PromptRecord:
        node = next((item for item in snapshot.nodes if item.node_id == node_id), None)
        if node is None:
            raise ValueError(f"unknown Roadmap node: {node_id}")
        task = f"Recall Roadmap node {node.node_id}: {node.title}"
        if node.capabilities:
            task += f"; capabilities: {', '.join(node.capabilities)}"
        return self.memory.generate_task_recall(task)


def compare_snapshots(
    previous: RoadmapSnapshot | None,
    current: RoadmapSnapshot,
) -> RoadmapDifferential:
    if previous is None:
        new_nodes = [node.node_id for node in current.nodes]
        return RoadmapDifferential(
            generated_at=current.generated_at,
            current_snapshot_id=current.snapshot_id,
            new_nodes=new_nodes,
            new_branches=sorted({node.branch_type.value for node in current.nodes}),
            new_decisions=[node.node_id for node in current.nodes if node.node_type is NodeType.DECISION],
            new_evidence=[node.node_id for node in current.nodes if node.evidence_ids],
            new_checkpoints=[node.node_id for node in current.nodes if node.node_type is NodeType.CHECKPOINT],
            unresolved_items=current.partial_reasons,
        )
    old = {node.node_id: node for node in previous.nodes}
    new = {node.node_id: node for node in current.nodes}
    added = sorted(set(new) - set(old))
    changed = sorted(
        node_id
        for node_id in set(old) & set(new)
        if old[node_id].logical_fingerprint() != new[node_id].logical_fingerprint()
    )
    proof_changes = [
        node_id
        for node_id in changed
        if (
            old[node_id].proof_badges != new[node_id].proof_badges
            or old[node_id].completed != new[node_id].completed
            or old[node_id].status != new[node_id].status
        )
    ]
    old_branches = {node.branch_type.value for node in previous.nodes}
    current_oldest_boundary = max((node.occurred_at for node in previous.nodes), default="")
    missing = []
    for node_id in sorted(set(old) - set(new)):
        node = old[node_id]
        classification = "SOURCE_MISSING"
        if ProofBadge.SUPERSEDED in node.proof_badges:
            classification = "SUPERSEDED"
        elif node.metadata.get("merged_into"):
            classification = "MERGED"
        elif node.metadata.get("reclassified_as"):
            classification = "RECLASSIFIED"
        missing.append(MissingNode(node_id=node_id, classification=classification, previous_title=node.title))
    return RoadmapDifferential(
        generated_at=current.generated_at,
        previous_snapshot_id=previous.snapshot_id,
        current_snapshot_id=current.snapshot_id,
        new_nodes=added,
        changed_nodes=changed,
        new_branches=sorted({new[node_id].branch_type.value for node_id in added} - old_branches),
        proof_state_changes=proof_changes,
        new_decisions=[node_id for node_id in added if new[node_id].node_type is NodeType.DECISION],
        new_evidence=[node_id for node_id in added if new[node_id].evidence_ids],
        new_checkpoints=[node_id for node_id in added if new[node_id].node_type is NodeType.CHECKPOINT],
        recovered_historical_nodes=[node_id for node_id in added if new[node_id].occurred_at < current_oldest_boundary],
        missing_nodes=missing,
        unresolved_items=current.partial_reasons,
    )


def roadmap_statistics(
    nodes: Sequence[RoadmapNode], edges: Sequence[RoadmapEdge]
) -> RoadmapStatistics:
    return RoadmapStatistics(
        nodes=len(nodes),
        edges=len(edges),
        stages=sum(node.node_type is NodeType.STAGE for node in nodes),
        subsystems=sum(node.node_type is NodeType.SUBSYSTEM for node in nodes),
        decisions=sum(bool(node.decision_ids) or node.node_type is NodeType.DECISION for node in nodes),
        implementations=sum(node.node_type in {NodeType.IMPLEMENTATION, NodeType.REFACTOR} for node in nodes),
        tests_probes=sum(node.node_type in {NodeType.TEST, NodeType.PROBE, NodeType.RETEST} for node in nodes),
        field_tests=sum(node.node_type is NodeType.FIELD_TEST for node in nodes),
        failures_root_causes_fixes=sum(node.node_type in {NodeType.FAILURE, NodeType.ROOT_CAUSE, NodeType.FIX} for node in nodes),
        field_proven=sum(ProofBadge.FIELD_PROVEN in node.proof_badges for node in nodes),
        superseded_rejected_removed=sum(any(badge in node.proof_badges for badge in (ProofBadge.SUPERSEDED, ProofBadge.REJECTED, ProofBadge.REMOVED, ProofBadge.DISCONNECTED)) for node in nodes),
        guard_events=sum(node.node_type is NodeType.GUARD_EVENT for node in nodes),
        checkpoints=sum(node.node_type is NodeType.CHECKPOINT for node in nodes),
        planned=sum(node.node_type is NodeType.PLANNED for node in nodes),
    )


def _node_sort_key(node: RoadmapNode) -> tuple[str, int, str]:
    order = {
        NodeType.PROJECT: 0,
        NodeType.STAGE: 1,
        NodeType.SUBSYSTEM: 2,
        NodeType.DECISION: 3,
        NodeType.IMPLEMENTATION: 4,
        NodeType.REFACTOR: 5,
        NodeType.TEST: 6,
        NodeType.PROBE: 7,
        NodeType.FIELD_TEST: 8,
        NodeType.FAILURE: 9,
        NodeType.ROOT_CAUSE: 10,
        NodeType.FIX: 11,
        NodeType.RETEST: 12,
        NodeType.MILESTONE: 13,
        NodeType.CHECKPOINT: 14,
        NodeType.SUPERSESSION: 15,
        NodeType.REJECTION: 16,
        NodeType.REMOVAL: 17,
        NodeType.DISCONNECTION: 18,
        NodeType.GUARD_EVENT: 19,
        NodeType.PLANNED: 20,
        NodeType.CANONICAL: 21,
        NodeType.HISTORICAL_RECONNECT: 22,
        NodeType.RECOVERED_IDEA: 23,
        NodeType.RETIREMENT: 24,
    }
    return node.occurred_at, order[node.node_type], node.node_id


def _provenance_category(source_item_id: object) -> str:
    value = str(source_item_id or "")
    for prefix, category in (
        ("git:", "GIT"),
        ("evidence:", "EVIDENCE"),
        ("document:decision:", "DECISION"),
        ("document:", "DECISION"),
        ("chatgpt:", "CHAT"),
        ("codex:", "CODEX"),
        ("runtime:", "LOG"),
    ):
        if value.startswith(prefix):
            return category
    return "GUARD"


def _provenance_date(provenance: Sequence[ProvenancePointer]) -> str:
    values = []
    for item in provenance:
        pointer = item.pointer
        for key in ("timestamp_utc", "decision_date", "created_at", "mtime_utc"):
            if pointer.get(key):
                values.append(_iso_date(pointer[key]))
    return min(values, default="2026-08-01T00:00:00+00:00")


def _decision_node_type(status: str) -> NodeType:
    upper = status.upper()
    if "REJECTED" in upper:
        return NodeType.REJECTION
    if "SUPERSEDED" in upper:
        return NodeType.SUPERSESSION
    return NodeType.DECISION


def _implementation_node_type(status: str) -> NodeType:
    upper = status.upper()
    if "REMOVED" in upper:
        return NodeType.REMOVAL
    if "DISCONNECTED" in upper:
        return NodeType.DISCONNECTION
    if "SUPERSEDED" in upper:
        return NodeType.SUPERSESSION
    if "PROBE" in upper:
        return NodeType.PROBE
    return NodeType.IMPLEMENTATION


def _derive_defect_chains(
    implementations: Sequence[Mapping[str, Any]],
) -> tuple[list[RoadmapNode], list[RoadmapEdge]]:
    nodes: list[RoadmapNode] = []
    edges: list[RoadmapEdge] = []
    ordered = sorted(implementations, key=lambda item: (str(item["date"]), str(item["id"])))
    for index, implementation in enumerate(ordered):
        for defect_index, defect in enumerate(implementation.get("defects", [])):
            defect_text = _safe_text(defect, fallback="Recorded implementation defect")
            later = next(
                (
                    candidate
                    for candidate in ordered[index + 1 :]
                    if set(implementation.get("capabilities", []))
                    & set(candidate.get("capabilities", []))
                    and any(
                        word.casefold() in str(candidate.get("title", "")).casefold()
                        for word in re.findall(r"[A-Za-z0-9_]{5,}", defect_text)
                    )
                ),
                None,
            )
            event_time = str(later["date"] if later else implementation["date"])
            base = canonical_sha256([implementation["id"], defect_index, defect_text])[:20].casefold()
            failure_id = f"failure:{base}"
            root_id = f"root-cause:{base}"
            provenance = list(implementation.get("provenance", []))
            nodes.append(
                RoadmapNode(
                    node_id=failure_id,
                    node_type=NodeType.FAILURE,
                    title=f"Observed defect · {defect_text}",
                    description=f"Bounded defect retained from {implementation['id']}.",
                    occurred_at=event_time,
                    branch_type=BranchType.TEST_EXPERIMENT,
                    status="FAILED_OBSERVATION",
                    proof_badges=[ProofBadge.FAILED],
                    completed=True,
                    capabilities=list(implementation.get("capabilities", [])),
                    parent_ids=[str(implementation["node_id"])],
                    provenance=provenance,
                )
            )
            nodes.append(
                RoadmapNode(
                    node_id=root_id,
                    node_type=NodeType.ROOT_CAUSE,
                    title=f"Root cause boundary · {defect_text}",
                    description="Derived presentation node backed by the Guard implementation defect record.",
                    occurred_at=event_time,
                    branch_type=BranchType.TEST_EXPERIMENT,
                    status="ROOT_CAUSE_RECORDED",
                    completed=True,
                    capabilities=list(implementation.get("capabilities", [])),
                    parent_ids=[failure_id],
                    provenance=provenance,
                )
            )
            if later:
                fix_id = f"fix:{later['id']}:{base}"
                nodes.append(
                    RoadmapNode(
                        node_id=fix_id,
                        node_type=NodeType.FIX,
                        title=f"Fix · {later['title']}",
                        description=f"Later overlapping Guard implementation {later['id']} addresses the recorded defect boundary.",
                        occurred_at=str(later["date"]),
                        branch_type=BranchType.TEST_EXPERIMENT,
                        status="IMPLEMENTED",
                        proof_badges=[ProofBadge.IMPLEMENTED],
                        completed=False,
                        capabilities=list(later.get("capabilities", [])),
                        parent_ids=[root_id],
                        provenance=list(later.get("provenance", [])),
                    )
                )
                for evidence in later.get("evidence", []):
                    retest_id = f"retest:{later['id']}:{evidence}"
                    nodes.append(
                        RoadmapNode(
                            node_id=retest_id,
                            node_type=NodeType.RETEST,
                            title=f"Retest / proof · {evidence}",
                            description=f"Guard evidence linked to {later['id']}.",
                            occurred_at=str(later["date"]),
                            branch_type=BranchType.TEST_EXPERIMENT,
                            status="FIELD_PROVEN",
                            proof_badges=[ProofBadge.TESTED, ProofBadge.FIELD_PROVEN],
                            completed=True,
                            capabilities=list(later.get("capabilities", [])),
                            evidence_ids=[str(evidence)],
                            parent_ids=[fix_id],
                            provenance=list(later.get("provenance", [])),
                        )
                    )
    return nodes, edges
