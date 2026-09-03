from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from tools.orion_arch_guard.fingerprints import canonical_sha256


class RoadmapState(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    REFRESH_REQUIRED = "REFRESH_REQUIRED"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


class NodeType(StrEnum):
    PROJECT = "PROJECT"
    STAGE = "STAGE"
    SUBSYSTEM = "SUBSYSTEM"
    DECISION = "DECISION"
    IMPLEMENTATION = "IMPLEMENTATION"
    REFACTOR = "REFACTOR"
    TEST = "TEST"
    PROBE = "PROBE"
    FIELD_TEST = "FIELD_TEST"
    FAILURE = "FAILURE"
    ROOT_CAUSE = "ROOT_CAUSE"
    FIX = "FIX"
    RETEST = "RETEST"
    MILESTONE = "MILESTONE"
    CHECKPOINT = "CHECKPOINT"
    SUPERSESSION = "SUPERSESSION"
    REJECTION = "REJECTION"
    REMOVAL = "REMOVAL"
    DISCONNECTION = "DISCONNECTION"
    GUARD_EVENT = "GUARD_EVENT"
    PLANNED = "PLANNED"


class BranchType(StrEnum):
    MAIN = "MAIN"
    TEST_EXPERIMENT = "TEST_EXPERIMENT"
    HISTORICAL_ALTERNATIVE = "HISTORICAL_ALTERNATIVE"
    GOVERNANCE = "GOVERNANCE"
    FUTURE = "FUTURE"


class ProofBadge(StrEnum):
    IMPLEMENTED = "IMPLEMENTED"
    TESTED = "TESTED"
    AUTOMATED_PROVEN = "AUTOMATED_PROVEN"
    PROBE_PROVEN = "PROBE_PROVEN"
    FIELD_PROVEN = "FIELD_PROVEN"
    HUMAN_CLEAR = "HUMAN_CLEAR"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    REMOVED = "REMOVED"
    DISCONNECTED = "DISCONNECTED"


class ProvenancePointer(BaseModel):
    category: str
    source_item_id: str | None = None
    pointer: dict[str, Any] = Field(default_factory=dict)
    confidence: str = "HIGH"


class RoadmapNode(BaseModel):
    node_id: str
    node_type: NodeType
    title: str
    description: str = ""
    occurred_at: str
    branch_type: BranchType = BranchType.MAIN
    status: str = "UNKNOWN"
    proof_badges: list[ProofBadge] = Field(default_factory=list)
    completed: bool = False
    current: bool = False
    capabilities: list[str] = Field(default_factory=list)
    subsystem: str | None = None
    decision_ids: list[str] = Field(default_factory=list)
    commit_shas: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    guard_report_ids: list[str] = Field(default_factory=list)
    verification_report_ids: list[str] = Field(default_factory=list)
    checkpoint_ids: list[str] = Field(default_factory=list)
    provider: str | None = None
    session_model: str | None = None
    parent_ids: list[str] = Field(default_factory=list)
    provenance: list[ProvenancePointer] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def logical_fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json")).casefold()


class RoadmapEdge(BaseModel):
    edge_id: str
    source_id: str
    target_id: str
    relationship: str
    branch_type: BranchType = BranchType.MAIN
    provenance: list[ProvenancePointer] = Field(default_factory=list)


class RoadmapStatistics(BaseModel):
    nodes: int = 0
    edges: int = 0
    stages: int = 0
    subsystems: int = 0
    decisions: int = 0
    implementations: int = 0
    tests_probes: int = 0
    field_tests: int = 0
    failures_root_causes_fixes: int = 0
    field_proven: int = 0
    superseded_rejected_removed: int = 0
    guard_events: int = 0
    checkpoints: int = 0
    planned: int = 0


class RoadmapSnapshot(BaseModel):
    schema_version: int = 1
    snapshot_id: str
    generated_at: str
    state: RoadmapState
    dependency_fingerprint: str
    content_fingerprint: str
    repository_head: str
    guard_report_id: str
    guard_graph_signature: str
    latest_checkpoint_id: str | None = None
    latest_evidence_id: str | None = None
    current_node_id: str
    nodes: list[RoadmapNode]
    edges: list[RoadmapEdge]
    statistics: RoadmapStatistics
    partial_reasons: list[str] = Field(default_factory=list)
    build_duration_ms: float = 0.0

    def fingerprint_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dependency_fingerprint": self.dependency_fingerprint,
            "repository_head": self.repository_head,
            "guard_graph_signature": self.guard_graph_signature,
            "latest_checkpoint_id": self.latest_checkpoint_id,
            "latest_evidence_id": self.latest_evidence_id,
            "current_node_id": self.current_node_id,
            "nodes": [item.model_dump(mode="json") for item in self.nodes],
            "edges": [item.model_dump(mode="json") for item in self.edges],
            "partial_reasons": self.partial_reasons,
        }

    def expected_fingerprint(self) -> str:
        return canonical_sha256(self.fingerprint_payload()).casefold()

    def validate_fingerprint(self) -> None:
        if self.content_fingerprint.casefold() != self.expected_fingerprint():
            raise ValueError(f"roadmap fingerprint mismatch: {self.snapshot_id}")


class DevelopmentPosition(BaseModel):
    development_stage: str
    development_status: str
    approved_next_step: str | None = None
    current_node_id: str
    approved_next_node_id: str | None = None
    derived_from_snapshot_id: str
    provenance: list[ProvenancePointer] = Field(default_factory=list)

    @property
    def checkpoint_stage(self) -> str:
        status = self.development_status.replace("_", " ")
        return f"{self.development_stage} · {status}"


class MissingNode(BaseModel):
    node_id: str
    classification: str
    previous_title: str


class RoadmapDifferential(BaseModel):
    generated_at: str
    previous_snapshot_id: str | None = None
    current_snapshot_id: str
    new_nodes: list[str] = Field(default_factory=list)
    changed_nodes: list[str] = Field(default_factory=list)
    new_branches: list[str] = Field(default_factory=list)
    proof_state_changes: list[str] = Field(default_factory=list)
    new_decisions: list[str] = Field(default_factory=list)
    new_evidence: list[str] = Field(default_factory=list)
    new_checkpoints: list[str] = Field(default_factory=list)
    recovered_historical_nodes: list[str] = Field(default_factory=list)
    missing_nodes: list[MissingNode] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)

    @property
    def unchanged(self) -> bool:
        return not any(
            (
                self.new_nodes,
                self.changed_nodes,
                self.new_branches,
                self.proof_state_changes,
                self.missing_nodes,
                self.unresolved_items,
            )
        )
