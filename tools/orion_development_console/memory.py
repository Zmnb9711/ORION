from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.orion_arch_guard.config import SourceConfig
from tools.orion_arch_guard.fingerprints import canonical_sha256
from tools.orion_arch_guard.guard import ArchitectureGuard, GuardMode, PreflightInput
from tools.orion_development_console.collectors import collect_git
from tools.orion_development_console.comparison import compare_checkpoints, render_comparison
from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.engine import VerificationEngine
from tools.orion_development_console.memory_models import (
    DevelopmentCheckpoint,
    PromptRecord,
    PromptType,
)
from tools.orion_development_console.memory_store import CheckpointStore, PromptStore
from tools.orion_development_console.privacy import sanitize


class AmbiguousTaskRecall(ValueError):
    def __init__(self, task: str, candidates: Sequence[str] = ()) -> None:
        self.task = task
        self.candidates = tuple(candidates)
        detail = ", ".join(self.candidates) or "no unambiguous capability"
        super().__init__(f"Task Recall requires clarification: {detail}")


TaskGuard = Callable[[str, str], Mapping[str, Any]]


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _ids(items: Sequence[Mapping[str, Any]] | None, key: str) -> list[str]:
    return sorted({str(item.get(key)) for item in items or () if item.get(key)})


def _decision_ids(guard: Mapping[str, Any], bucket: str) -> list[str]:
    decisions = guard.get("decisions")
    if not isinstance(decisions, Mapping):
        return []
    value = decisions.get(bucket)
    return _ids(value if isinstance(value, list) else [], "decision_id")


def _guard_capabilities(guard: Mapping[str, Any]) -> list[str]:
    value = guard.get("affected_capabilities")
    return _ids(value if isinstance(value, list) else [], "capability_id")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _guard_path(context: VerificationContext, report_id: str) -> Path:
    return context.guard_root / "reports" / f"{report_id}.json"


def load_guard_report(context: VerificationContext, report_id: str) -> dict[str, Any]:
    path = _guard_path(context, report_id)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("report_id") != report_id:
        raise ValueError(f"invalid Guard report: {report_id}")
    return value


def _checkpoint_id(now: datetime) -> str:
    return f"CP-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _prompt_id(now: datetime) -> str:
    return f"PR-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


class DevelopmentMemoryService:
    """Bounded development-memory orchestration for the dev-only Console."""

    def __init__(
        self,
        context: VerificationContext,
        *,
        engine: VerificationEngine | None = None,
        checkpoints: CheckpointStore | None = None,
        prompts: PromptStore | None = None,
        task_guard: TaskGuard | None = None,
        now: Callable[[], datetime] = _now_utc,
    ) -> None:
        self.context = context
        self.engine = engine or VerificationEngine(context)
        self.checkpoints = checkpoints or CheckpointStore(context.console_root)
        self.prompts = prompts or PromptStore(context.console_root)
        self.task_guard = task_guard or self._run_task_guard
        self.now = now

    def guard_report(self, report_id: str | None = None) -> dict[str, Any]:
        return load_guard_report(self.context, report_id or self.context.architecture_report_id)

    def current_git(self) -> dict[str, Any]:
        return dict(collect_git(self.context).details)

    def latest_checkpoint(self) -> DevelopmentCheckpoint | None:
        return self.checkpoints.latest()

    def latest_prompt(self) -> PromptRecord | None:
        return self.prompts.latest()

    def _verification_id(self) -> str | None:
        report = self.engine.cached_report()
        return report.verification_id if report else None

    def _recent_evidence(self) -> list[dict[str, Any]]:
        report = self.engine.cached_report()
        if report is None:
            return []
        observation = report.observation("evidence")
        if observation is None:
            return []
        details = observation.details
        return [
            sanitize(
                {
                    "verification_report_id": report.verification_id,
                    "count": details.get("evidence_zip_count"),
                    "latest_timestamp": details.get("latest_evidence_timestamp"),
                    "latest_build_sha": details.get("latest_evidence_build_sha"),
                    "state": observation.state.value,
                }
            )
        ]

    def build_checkpoint_candidate(
        self,
        *,
        development_stage: str,
        approved_next_step: str | None,
        completed_work: Sequence[str] = (),
        new_decisions: Sequence[str] = (),
        unvalidated_work: Sequence[str] = (),
        known_problems: Sequence[str] = (),
        risks: Sequence[str] = (),
    ) -> DevelopmentCheckpoint:
        stage = development_stage.strip()
        if not stage:
            raise ValueError("Current Development Stage requires explicit user input")
        next_step = approved_next_step.strip() if approved_next_step else None
        now = self.now().astimezone(UTC)
        guard = self.guard_report()
        git = self.current_git()
        implementations = guard.get("implementations")
        implementation_map = implementations if isinstance(implementations, Mapping) else {}
        previous_best = guard.get("previous_best")
        previous_best_map = previous_best if isinstance(previous_best, Mapping) else {}
        records = guard.get("implementation_records")
        implementation_records = records if isinstance(records, list) else []
        automated_or_probe = {
            str(item.get("implementation_id"))
            for item in implementation_records
            if isinstance(item, Mapping)
            and item.get("implementation_id")
            and str(item.get("historical_status")) in {"AUTOMATED_PROVEN", "PROBE_PROVEN", "PROBE"}
        }
        checkpoint = DevelopmentCheckpoint(
            checkpoint_id=_checkpoint_id(now),
            created_at=now.isoformat(),
            branch=str(git.get("branch") or "UNKNOWN"),
            head_sha=str(git.get("head") or "UNKNOWN"),
            guard_report_id=str(guard.get("report_id") or self.context.architecture_report_id),
            verification_report_id=self._verification_id(),
            development_stage=stage,
            approved_next_step=next_step,
            current_decisions=_decision_ids(guard, "CURRENT"),
            new_decisions=sorted(set(new_decisions)),
            superseded_decisions=_decision_ids(guard, "SUPERSEDED"),
            rejected_decisions=_decision_ids(guard, "REJECTED"),
            completed_work=sorted(set(completed_work)),
            field_proven=sorted(set(str(item) for item in implementation_map.get("FIELD_PROVEN", []))),
            probe_or_automated_proven=sorted(
                set(
                    str(item)
                    for status in ("PROBE",)
                    for item in implementation_map.get(status, [])
                )
                | automated_or_probe
            ),
            unvalidated_work=sorted(set(unvalidated_work)),
            implementations=sorted(set(str(item) for item in implementation_map.get("CURRENT", []))),
            previous_best_mechanisms=sorted(
                set(str(item) for item in previous_best_map.get("previous_best_mechanisms", []))
            ),
            do_not_rebuild=[
                "Phase 1 Local Environment Verification",
                "Architecture Guard AG-0/AG-1/AG-2/AG-3",
                "Master Decision Register and Master Architecture Checkpoint",
                "field-proven mechanisms named by the applicable Guard",
            ],
            do_not_reinvent=[
                "capability-centric Guard retrieval",
                "bounded Evidence discovery and provenance",
                "ORION Launcher visual language",
                "private atomic report storage",
            ],
            recent_evidence=self._recent_evidence(),
            known_problems=sorted(set(known_problems)),
            risks=sorted(set(risks)),
            provenance=[
                f"guard:{guard.get('report_id')}",
                f"git:{git.get('head')}",
                "docs/orion-master-decision-register-2026-09-01.md",
                "docs/orion-master-architecture-checkpoint-2026-09-01.md",
                "docs/ORION_PROJECT_MEMORY.md",
                "docs/orion-development-history-2026-09-02.md",
                *( [f"verification:{self._verification_id()}"] if self._verification_id() else [] ),
            ],
            content_fingerprint="",
        )
        return checkpoint.model_copy(
            update={"content_fingerprint": checkpoint.expected_fingerprint()}
        )

    def save_checkpoint(self, candidate: DevelopmentCheckpoint) -> Path:
        return self.checkpoints.save_create_once(candidate)

    def _new_prompt(
        self,
        *,
        prompt_type: PromptType,
        content: str,
        guard_report_id: str,
        head_sha: str,
        checkpoint_id: str | None = None,
        task: str | None = None,
        capabilities: Sequence[str] = (),
        provenance: Sequence[str] = (),
    ) -> PromptRecord:
        now = self.now().astimezone(UTC)
        record = PromptRecord(
            prompt_id=_prompt_id(now),
            prompt_type=prompt_type,
            created_at=now.isoformat(),
            checkpoint_id=checkpoint_id,
            guard_report_id=guard_report_id,
            verification_report_id=self._verification_id(),
            head_sha=head_sha,
            task=task,
            capabilities=sorted(set(capabilities)),
            content=content.strip() + "\n",
            content_fingerprint="",
            provenance=list(provenance),
        )
        record = record.model_copy(update={"content_fingerprint": record.expected_fingerprint()})
        self.prompts.save_create_once(record)
        return record

    def generate_full_recall(self) -> PromptRecord:
        guard = self.guard_report()
        git = self.current_git()
        checkpoint = self.latest_checkpoint()
        verification = self.engine.cached_report()
        history = _mapping(guard.get("history_coverage"))
        previous_best = _mapping(guard.get("previous_best"))
        stage = checkpoint.development_stage if checkpoint else "NOT RECORDED"
        next_step = checkpoint.approved_next_step if checkpoint and checkpoint.approved_next_step else "NOT RECORDED — USER CONFIRMATION REQUIRED"
        content = f"""ORION ARCHITECTURE GUARD: ON — {guard.get('report_id')}

# ORION FULL DEVELOPMENT RECALL

Repository: {self.context.repository_root}
Git: {git.get('branch')} @ {git.get('head')}
History verification: {history.get('overall', 'UNKNOWN')}
Local verification report: {verification.verification_id if verification else 'NOT_CHECKED'}
Latest checkpoint: {checkpoint.checkpoint_id if checkpoint else 'NONE'}

## Current architecture
MODEL C remains the durable baseline: Core owns authoritative facts and protected operational behavior; AI providers remain bounded formulation/planning adapters.

## Decisions
Current: {', '.join(_decision_ids(guard, 'CURRENT')) or 'NONE'}
Superseded: {', '.join(_decision_ids(guard, 'SUPERSEDED')) or 'NONE'}
Rejected: {', '.join(_decision_ids(guard, 'REJECTED')) or 'NONE'}

## Previous implementations and Previous Best
Previous implementations: {', '.join(str(item) for item in previous_best.get('previous_implementations_found', [])) or 'NONE'}
Previous Best mechanisms: {', '.join(str(item) for item in previous_best.get('previous_best_mechanisms', [])) or 'NONE'}

## DO NOT REBUILD
Phase 1 verification; Architecture Guard; authoritative Master/Decision history; applicable field-proven mechanisms.

## DO NOT REINVENT
Capability-centric retrieval; bounded provenance; Evidence discovery; ORION Launcher visual language; private atomic record storage.

## Current development position
Stage: {stage}
Approved next step: {next_step}
Known problems/risks: {', '.join(checkpoint.known_problems + checkpoint.risks) if checkpoint else 'No approved checkpoint summary exists'}

## Continuation instruction
Recover only the relevant bounded context through Guard/L0/index/graph. Preserve the three truth domains. Do not treat an old checkpoint as current-machine authority. Apply D71: RECONNECT → ADAPT → EXTEND → REFACTOR → REPLACE.

## Provenance
Guard {guard.get('report_id')}; Git {git.get('head')}; Master Decision Register; Master Architecture Checkpoint; Project Memory; Development History; {f'checkpoint {checkpoint.checkpoint_id}' if checkpoint else 'no checkpoint'}; {f'verification {verification.verification_id}' if verification else 'no verification report'}.
"""
        return self._new_prompt(
            prompt_type=PromptType.FULL_RECALL,
            content=content,
            guard_report_id=str(guard.get("report_id")),
            head_sha=str(git.get("head")),
            checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
            capabilities=_guard_capabilities(guard),
            provenance=[f"guard:{guard.get('report_id')}", f"git:{git.get('head')}"],
        )

    def _run_task_guard(self, task: str, head_sha: str) -> Mapping[str, Any]:
        database = SourceConfig.defaults(self.context.repository_root).resolved_index_path
        guard = ArchitectureGuard(database)
        try:
            stored = guard.preflight(
                PreflightInput(
                    mode=GuardMode.FULL,
                    task_title=f"Task Recall: {task}",
                    task_description="Capability-centric historical retrieval for a visible recovery prompt.",
                    proposed_change="No implementation; retrieve relevant history only.",
                    affected_files=(),
                    explicit_capabilities=(),
                    current_head=head_sha,
                    user_constraints=("No architecture change or hidden context transfer.",),
                ),
                store=True,
            )
        finally:
            guard.close()
        return stored.result

    def generate_task_recall(self, task: str) -> PromptRecord:
        normalized = task.strip()
        if not normalized:
            raise AmbiguousTaskRecall(task)
        git = self.current_git()
        guard = dict(self.task_guard(normalized, str(git.get("head"))))
        capabilities = _guard_capabilities(guard)
        candidates = _ids(
            guard.get("candidate_capabilities") if isinstance(guard.get("candidate_capabilities"), list) else [],
            "capability_id",
        )
        if not capabilities or bool(guard.get("requires_user_decision")):
            raise AmbiguousTaskRecall(normalized, candidates or capabilities)
        previous_best = _mapping(guard.get("previous_best"))
        implementations = _mapping(guard.get("implementations"))
        evidence_reuse = _mapping(guard.get("evidence_reuse"))
        content = f"""ORION ARCHITECTURE GUARD: ON — {guard.get('report_id')}

# ORION TASK RECALL

Task: {normalized}
Capabilities resolved by AG-2/AG-3: {', '.join(capabilities)}
Gate: {guard.get('gate')}
History coverage: {(guard.get('history_coverage') or {}).get('overall', 'UNKNOWN')}

Current decisions: {', '.join(_decision_ids(guard, 'CURRENT')) or 'NONE'}
Superseded decisions: {', '.join(_decision_ids(guard, 'SUPERSEDED')) or 'NONE'}
Rejected decisions: {', '.join(_decision_ids(guard, 'REJECTED')) or 'NONE'}
Current implementations: {', '.join(str(item) for item in implementations.get('CURRENT', [])) or 'NONE'}
Previous implementations: {', '.join(str(item) for item in previous_best.get('previous_implementations_found', [])) or 'NONE'}
Previous Best mechanisms: {', '.join(str(item) for item in previous_best.get('previous_best_mechanisms', [])) or 'NONE'}
Evidence reusable: {evidence_reuse.get('evidence_remains_valid', False)}
Conflicts: {len(guard.get('conflicts') or [])}

Recover the task from these capability-linked records and exact Guard provenance. Do not rebuild protected or field-proven mechanisms. Do not infer unrelated history from keyword similarity alone.
"""
        return self._new_prompt(
            prompt_type=PromptType.TASK_RECALL,
            content=content,
            guard_report_id=str(guard.get("report_id")),
            head_sha=str(git.get("head")),
            task=normalized,
            capabilities=capabilities,
            provenance=[f"guard:{guard.get('report_id')}", f"git:{git.get('head')}"],
        )

    def checkpoint_recovery_prompt(self, checkpoint: DevelopmentCheckpoint) -> PromptRecord:
        content = f"""ORION ARCHITECTURE GUARD: ON — {checkpoint.guard_report_id}

# ORION CHECKPOINT RECOVERY

Checkpoint: {checkpoint.checkpoint_id}
Created: {checkpoint.created_at}
Git: {checkpoint.branch} @ {checkpoint.head_sha}
Development stage: {checkpoint.development_stage}
Approved next step: {checkpoint.approved_next_step or 'NOT RECORDED — USER CONFIRMATION REQUIRED'}
Decisions: {', '.join(checkpoint.current_decisions) or 'NONE'}
Implementations: {', '.join(checkpoint.implementations) or 'NONE'}
Field proven: {', '.join(checkpoint.field_proven) or 'NONE'}
Previous Best: {', '.join(checkpoint.previous_best_mechanisms) or 'NONE'}
DO NOT REBUILD: {'; '.join(checkpoint.do_not_rebuild)}
DO NOT REINVENT: {'; '.join(checkpoint.do_not_reinvent)}
Known problems/risks: {'; '.join(checkpoint.known_problems + checkpoint.risks) or 'NONE'}

This checkpoint is historical truth only. Re-verify current Git, Guard and machine state before implementation.
"""
        return self._new_prompt(
            prompt_type=PromptType.CHECKPOINT_RECOVERY,
            content=content,
            guard_report_id=checkpoint.guard_report_id,
            head_sha=checkpoint.head_sha,
            checkpoint_id=checkpoint.checkpoint_id,
            provenance=checkpoint.provenance,
        )

    def generate_continue(self) -> PromptRecord:
        checkpoint = self.latest_checkpoint()
        if checkpoint is None:
            raise ValueError("No explicitly saved checkpoint exists")
        if not checkpoint.approved_next_step:
            raise ValueError("Approved Next Step is missing; user confirmation is required")
        current = self.build_checkpoint_candidate(
            development_stage=checkpoint.development_stage,
            approved_next_step=checkpoint.approved_next_step,
        )
        comparison = compare_checkpoints(checkpoint, current)
        content = f"""ORION ARCHITECTURE GUARD: ON — {current.guard_report_id}

# ORION CONTINUE DEVELOPMENT

Resume from explicitly saved checkpoint {checkpoint.checkpoint_id}.
Checkpoint Git: {checkpoint.branch} @ {checkpoint.head_sha}
Current verified Git: {current.branch} @ {current.head_sha}
Current verification report: {current.verification_report_id or 'NOT_CHECKED'}
Development stage: {checkpoint.development_stage}
Approved next step: {checkpoint.approved_next_step}

## Meaningful change since checkpoint
{render_comparison(comparison)}

## Protected continuity
DO NOT REBUILD: {'; '.join(checkpoint.do_not_rebuild)}
DO NOT REINVENT: {'; '.join(checkpoint.do_not_reinvent)}
Previous Best: {', '.join(checkpoint.previous_best_mechanisms) or 'NONE'}

Continue only the approved next step. Re-run Architecture Guard before any newly discovered architecture decision. Preserve historical, current-development and current-machine truth as separate domains.
"""
        return self._new_prompt(
            prompt_type=PromptType.CONTINUE,
            content=content,
            guard_report_id=current.guard_report_id,
            head_sha=current.head_sha,
            checkpoint_id=checkpoint.checkpoint_id,
            capabilities=_guard_capabilities(self.guard_report()),
            provenance=[*checkpoint.provenance, f"comparison:{checkpoint.checkpoint_id}:{current.checkpoint_id}"],
        )

    def regenerate_prompt(self, record: PromptRecord) -> PromptRecord:
        if record.prompt_type is PromptType.FULL_RECALL:
            return self.generate_full_recall()
        if record.prompt_type is PromptType.TASK_RECALL:
            return self.generate_task_recall(record.task or "")
        if record.prompt_type is PromptType.CONTINUE:
            return self.generate_continue()
        if record.checkpoint_id:
            return self.checkpoint_recovery_prompt(self.checkpoints.load(record.checkpoint_id))
        raise ValueError("Prompt cannot be regenerated from current state")
