from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from tools.orion_arch_guard.fingerprints import canonical_sha256


class PromptType(StrEnum):
    FULL_RECALL = "FULL_RECALL"
    TASK_RECALL = "TASK_RECALL"
    CONTINUE = "CONTINUE"
    CHECKPOINT_RECOVERY = "CHECKPOINT_RECOVERY"


class DevelopmentCheckpoint(BaseModel):
    schema_version: int = 1
    checkpoint_id: str
    created_at: str
    branch: str
    head_sha: str
    guard_report_id: str
    verification_report_id: str | None = None
    development_stage: str
    approved_next_step: str | None = None
    current_decisions: list[str] = Field(default_factory=list)
    new_decisions: list[str] = Field(default_factory=list)
    superseded_decisions: list[str] = Field(default_factory=list)
    rejected_decisions: list[str] = Field(default_factory=list)
    completed_work: list[str] = Field(default_factory=list)
    field_proven: list[str] = Field(default_factory=list)
    probe_or_automated_proven: list[str] = Field(default_factory=list)
    unvalidated_work: list[str] = Field(default_factory=list)
    implementations: list[str] = Field(default_factory=list)
    previous_best_mechanisms: list[str] = Field(default_factory=list)
    do_not_rebuild: list[str] = Field(default_factory=list)
    do_not_reinvent: list[str] = Field(default_factory=list)
    recent_evidence: list[dict[str, Any]] = Field(default_factory=list)
    known_problems: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)
    content_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_fingerprint"})

    def expected_fingerprint(self) -> str:
        return canonical_sha256(self.fingerprint_payload()).casefold()

    def validate_fingerprint(self) -> None:
        if self.content_fingerprint.casefold() != self.expected_fingerprint():
            raise ValueError(f"checkpoint fingerprint mismatch: {self.checkpoint_id}")


class PromptRecord(BaseModel):
    schema_version: int = 1
    prompt_id: str
    prompt_type: PromptType
    created_at: str
    checkpoint_id: str | None = None
    guard_report_id: str
    verification_report_id: str | None = None
    head_sha: str
    task: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    content: str
    content_fingerprint: str
    provenance: list[str] = Field(default_factory=list)

    def expected_fingerprint(self) -> str:
        return canonical_sha256({"content": self.content}).casefold()

    def validate_fingerprint(self) -> None:
        if self.content_fingerprint.casefold() != self.expected_fingerprint():
            raise ValueError(f"prompt fingerprint mismatch: {self.prompt_id}")


class SemanticChange(BaseModel):
    category: str
    before: str
    after: str
    significance: str = "MEANINGFUL"


class CheckpointComparison(BaseModel):
    left_id: str
    right_id: str
    changes: list[SemanticChange] = Field(default_factory=list)
    unchanged_head_only: bool = False

    @property
    def has_meaningful_changes(self) -> bool:
        return bool(self.changes)
