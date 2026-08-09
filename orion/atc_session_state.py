from __future__ import annotations

from threading import RLock
from uuid import UUID

from pydantic import BaseModel, Field

from orion.atc_core import AtcSessionIdentity
from orion.atc_operations import (
    CommitmentState,
    OperationalOverlay,
    SequencedTrafficEntry,
    TrafficConflict,
    TrafficPriority,
)


class AtcRuntimeSession(BaseModel):
    identity: AtcSessionIdentity
    procedural_state: str = Field(min_length=1, max_length=160)
    overlays: set[OperationalOverlay] = Field(default_factory=set)
    priority: TrafficPriority = TrafficPriority.NORMAL
    commitment: CommitmentState = CommitmentState.UNCOMMITTED
    revision: int = Field(default=1, ge=1)
    last_reason: str = Field(default="session created", min_length=1, max_length=500)

    def transition(self, procedural_state: str, *, reason: str) -> None:
        if not procedural_state:
            raise ValueError("Procedural state must not be empty")
        self.procedural_state = procedural_state
        self.revision += 1
        self.last_reason = reason

    def add_overlay(self, overlay: OperationalOverlay, *, reason: str) -> None:
        self.overlays.add(overlay)
        self.revision += 1
        self.last_reason = reason

    def remove_overlay(self, overlay: OperationalOverlay, *, reason: str) -> None:
        self.overlays.discard(overlay)
        self.revision += 1
        self.last_reason = reason

    def set_priority(self, priority: TrafficPriority, *, reason: str) -> None:
        self.priority = priority
        self.revision += 1
        self.last_reason = reason

    def set_commitment(self, commitment: CommitmentState, *, reason: str) -> None:
        if commitment < self.commitment:
            raise ValueError("Commitment cannot be reduced implicitly")
        self.commitment = commitment
        self.revision += 1
        self.last_reason = reason


class AtcSessionRuntimeStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[UUID, AtcRuntimeSession] = {}

    def create(self, session: AtcRuntimeSession) -> AtcRuntimeSession:
        with self._lock:
            session_id = session.identity.session_id
            if session_id in self._sessions:
                raise ValueError("ATC runtime session already exists")
            self._sessions[session_id] = session.model_copy(deep=True)
            return session.model_copy(deep=True)

    def get(self, session_id: UUID) -> AtcRuntimeSession | None:
        with self._lock:
            item = self._sessions.get(session_id)
            return item.model_copy(deep=True) if item else None

    def replace(self, session: AtcRuntimeSession) -> AtcRuntimeSession:
        with self._lock:
            session_id = session.identity.session_id
            if session_id not in self._sessions:
                raise KeyError("ATC runtime session not found")
            self._sessions[session_id] = session.model_copy(deep=True)
            return session.model_copy(deep=True)

    def remove(self, session_id: UUID) -> AtcRuntimeSession | None:
        with self._lock:
            item = self._sessions.pop(session_id, None)
            return item.model_copy(deep=True) if item else None


class GenericSequencingPolicy:
    """Domain-neutral ordering using safety priority and commitment independently."""

    def order(self, entries: list[SequencedTrafficEntry]) -> list[SequencedTrafficEntry]:
        return sorted(
            entries,
            key=lambda entry: (
                -int(entry.priority),
                -int(entry.commitment),
                entry.sequence_index,
                str(entry.session_id),
            ),
        )

    def may_displace(
        self,
        *,
        candidate: SequencedTrafficEntry,
        incumbent: SequencedTrafficEntry,
    ) -> bool:
        if incumbent.commitment is CommitmentState.IRREVERSIBLE:
            return False
        if incumbent.commitment >= CommitmentState.PHYSICALLY_COMMITTED:
            return (
                candidate.priority is TrafficPriority.EMERGENCY
                and candidate.commitment >= incumbent.commitment
            )
        if candidate.priority != incumbent.priority:
            return candidate.priority > incumbent.priority
        if candidate.commitment != incumbent.commitment:
            return candidate.commitment > incumbent.commitment
        return candidate.sequence_index < incumbent.sequence_index


class ConflictResolutionAction:
    DELAY = "delay"
    RESEQUENCE = "resequence"
    SUSPEND_NEW_CLEARANCES = "suspend_new_clearances"
    PROTECT_COMMITTED = "protect_committed"


class GenericConflictResolutionPolicy:
    """Conservative resolution policy shared by airport and carrier engines."""

    def resolve(
        self,
        conflict: TrafficConflict,
        entries: dict[UUID, SequencedTrafficEntry],
    ) -> tuple[str, str]:
        involved = [entries[sid] for sid in conflict.sessions if sid in entries]
        if not involved:
            return (
                ConflictResolutionAction.SUSPEND_NEW_CLEARANCES,
                "conflict has no resolvable traffic state",
            )
        if any(entry.commitment is CommitmentState.IRREVERSIBLE for entry in involved):
            return ConflictResolutionAction.PROTECT_COMMITTED, "irreversible traffic is protected"
        if any(entry.commitment >= CommitmentState.PHYSICALLY_COMMITTED for entry in involved):
            return (
                ConflictResolutionAction.PROTECT_COMMITTED,
                "physically committed traffic is protected",
            )
        if len({entry.priority for entry in involved}) > 1:
            return (
                ConflictResolutionAction.RESEQUENCE,
                "higher-priority uncommitted traffic may be advanced",
            )
        return (
            ConflictResolutionAction.DELAY,
            "equal-priority uncommitted traffic is delayed conservatively",
        )
