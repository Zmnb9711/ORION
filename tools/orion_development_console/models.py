from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TruthDomain(StrEnum):
    HISTORICAL = "HISTORICAL_TRUTH"
    DEVELOPMENT = "CURRENT_DEVELOPMENT_STATE"
    MACHINE = "CURRENT_MACHINE_STATE"


class VerificationState(StrEnum):
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    CHANGED = "CHANGED"
    NEW = "NEW"
    MISSING = "MISSING"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"
    NOT_CHECKED = "NOT_CHECKED"


class FactState(StrEnum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"
    NOT_CHECKED = "NOT_CHECKED"


class ComparisonState(StrEnum):
    MATCH = "MATCH"
    DIFFERENT = "DIFFERENT"
    UNKNOWN = "UNKNOWN"


class VerificationObservation(BaseModel):
    subject: str
    truth_domain: TruthDomain
    state: VerificationState
    verified_at: str
    verification_method: str
    fingerprint: str | None = None
    source_reference: str | None = None
    invalidated_by: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    installed: FactState = FactState.NOT_CHECKED
    configured: FactState = FactState.NOT_CHECKED
    running: FactState = FactState.NOT_CHECKED
    ready: FactState = FactState.NOT_CHECKED


class VerificationReport(BaseModel):
    schema_version: int = 1
    verification_id: str
    generated_at: str
    repository_head: str | None = None
    architecture_guard_report_id: str
    architecture_guard_gate: str
    observations: list[VerificationObservation]
    actions_not_performed: list[str]
    network_accessed: bool = False
    product_processes_launched: bool = False
    primary_history_modified: bool = False

    def observation(self, subject: str) -> VerificationObservation | None:
        return next((item for item in self.observations if item.subject == subject), None)

    @property
    def overall_state(self) -> VerificationState:
        states = {item.state for item in self.observations}
        for state in (
            VerificationState.ERROR,
            VerificationState.CHANGED,
            VerificationState.PARTIAL,
            VerificationState.STALE,
            VerificationState.UNKNOWN,
            VerificationState.NEW,
            VerificationState.MISSING,
        ):
            if state in states:
                return state
        return VerificationState.VERIFIED
