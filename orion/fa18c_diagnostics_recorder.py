from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class DiagnosticChange(BaseModel):
    id: int
    value: float
    previous: float | None = None


class DiagnosticPacket(BaseModel):
    mode: str
    aircraft_id: str
    range: dict[str, int] = Field(default_factory=dict)
    changes: list[DiagnosticChange] = Field(default_factory=list)


class MappingCandidate(BaseModel):
    argument_id: int
    score: int
    observations: int
    transitions: list[tuple[float | None, float]] = Field(default_factory=list)
    markers: list[str] = Field(default_factory=list)


class MappingReport(BaseModel):
    session_id: str
    label: str | None = None
    active_marker: str | None = None
    packet_count: int
    event_count: int
    candidates: list[MappingCandidate]
    markers: dict[str, list[int]] = Field(default_factory=dict)


@dataclass
class _Session:
    session_id: str
    label: str | None
    started_at: datetime
    active_marker: str | None = None
    packet_count: int = 0
    events: list[tuple[str | None, DiagnosticChange]] = field(default_factory=list)


class HornetDiagnosticsRecorder:
    def __init__(self) -> None:
        self._session: _Session | None = None

    def start(self, label: str | None = None) -> str:
        session_id = str(uuid4())
        self._session = _Session(session_id=session_id, label=label, started_at=datetime.now(timezone.utc))
        return session_id

    def stop(self) -> MappingReport | None:
        if self._session is None:
            return None
        report = self.report()
        self._session = None
        return report

    def clear(self) -> None:
        self._session = None

    def mark(self, label: str | None) -> None:
        if self._session is None:
            raise RuntimeError("No diagnostics session is active")
        self._session.active_marker = label.strip() if isinstance(label, str) and label.strip() else None

    def ingest(self, payload: object) -> int:
        if self._session is None or not isinstance(payload, dict):
            return 0
        try:
            packet = DiagnosticPacket.model_validate(payload)
        except Exception:
            return 0
        if packet.aircraft_id != "fa-18c" or packet.mode != "cockpit_argument_changes":
            return 0
        self._session.packet_count += 1
        for change in packet.changes:
            self._session.events.append((self._session.active_marker, change))
        return len(packet.changes)

    def report(self) -> MappingReport:
        if self._session is None:
            raise RuntimeError("No diagnostics session is active")

        by_id: dict[int, list[DiagnosticChange]] = defaultdict(list)
        marker_ids: dict[str, set[int]] = defaultdict(set)
        marker_counts: Counter[tuple[str, int]] = Counter()

        for marker, change in self._session.events:
            by_id[change.id].append(change)
            if marker:
                marker_ids[marker].add(change.id)
                marker_counts[(marker, change.id)] += 1

        candidates: list[MappingCandidate] = []
        for argument_id, changes in by_id.items():
            supported_markers = sorted(marker for marker, ids in marker_ids.items() if argument_id in ids)
            marker_support = len(supported_markers)
            strongest_marker_hits = max((marker_counts[(marker, argument_id)] for marker in marker_ids), default=0)
            score = len(changes) + (marker_support * 3) + (strongest_marker_hits * 2)
            candidates.append(
                MappingCandidate(
                    argument_id=argument_id,
                    score=score,
                    observations=len(changes),
                    transitions=[(item.previous, item.value) for item in changes[-64:]],
                    markers=supported_markers,
                )
            )

        candidates.sort(key=lambda item: (-item.score, -item.observations, item.argument_id))
        return MappingReport(
            session_id=self._session.session_id,
            label=self._session.label,
            active_marker=self._session.active_marker,
            packet_count=self._session.packet_count,
            event_count=len(self._session.events),
            candidates=candidates,
            markers={name: sorted(ids) for name, ids in marker_ids.items()},
        )


hornet_diagnostics_recorder = HornetDiagnosticsRecorder()
