from __future__ import annotations

from collections.abc import Iterable

from tools.orion_development_console.memory_models import (
    CheckpointComparison,
    DevelopmentCheckpoint,
    SemanticChange,
)


def _set_changes(category: str, left: Iterable[str], right: Iterable[str]) -> list[SemanticChange]:
    before = set(left)
    after = set(right)
    changes: list[SemanticChange] = []
    added = sorted(after - before)
    removed = sorted(before - after)
    if added or removed:
        changes.append(
            SemanticChange(
                category=category,
                before=", ".join(removed) or "—",
                after=", ".join(added) or "—",
            )
        )
    return changes


def compare_checkpoints(
    left: DevelopmentCheckpoint,
    right: DevelopmentCheckpoint,
) -> CheckpointComparison:
    changes: list[SemanticChange] = []
    pairs = (
        ("Guard", left.guard_report_id, right.guard_report_id),
        ("Development stage", left.development_stage, right.development_stage),
        ("Approved next step", left.approved_next_step or "NOT RECORDED", right.approved_next_step or "NOT RECORDED"),
    )
    for category, before, after in pairs:
        if before != after:
            changes.append(SemanticChange(category=category, before=before, after=after))
    for category, before, after in (
        ("Current decisions", left.current_decisions, right.current_decisions),
        ("Superseded decisions", left.superseded_decisions, right.superseded_decisions),
        ("Rejected decisions", left.rejected_decisions, right.rejected_decisions),
        ("Implementations", left.implementations, right.implementations),
        ("Previous Best", left.previous_best_mechanisms, right.previous_best_mechanisms),
        ("DO NOT REBUILD", left.do_not_rebuild, right.do_not_rebuild),
        ("DO NOT REINVENT", left.do_not_reinvent, right.do_not_reinvent),
        ("Known problems", left.known_problems, right.known_problems),
        ("Risks", left.risks, right.risks),
    ):
        changes.extend(_set_changes(category, before, after))

    left_proof = {
        **{item: "UNVALIDATED" for item in left.unvalidated_work},
        **{item: "AUTOMATED_OR_PROBE_PROVEN" for item in left.probe_or_automated_proven},
        **{item: "FIELD_PROVEN" for item in left.field_proven},
    }
    right_proof = {
        **{item: "UNVALIDATED" for item in right.unvalidated_work},
        **{item: "AUTOMATED_OR_PROBE_PROVEN" for item in right.probe_or_automated_proven},
        **{item: "FIELD_PROVEN" for item in right.field_proven},
    }
    for item in sorted(left_proof.keys() & right_proof.keys()):
        if left_proof[item] != right_proof[item]:
            changes.append(
                SemanticChange(
                    category=f"Proof state: {item}",
                    before=left_proof[item],
                    after=right_proof[item],
                    significance="PROOF_TRANSITION",
                )
            )
    changes.extend(_set_changes("Evidence", (str(item) for item in left.recent_evidence), (str(item) for item in right.recent_evidence)))

    meaningful_without_head = bool(changes)
    if left.head_sha != right.head_sha:
        changes.append(
            SemanticChange(
                category="Git HEAD",
                before=left.head_sha,
                after=right.head_sha,
                significance="CONTEXT" if meaningful_without_head else "HEAD_ONLY",
            )
        )
    return CheckpointComparison(
        left_id=left.checkpoint_id,
        right_id=right.checkpoint_id,
        changes=changes,
        unchanged_head_only=(left.head_sha != right.head_sha and not meaningful_without_head),
    )


def render_comparison(comparison: CheckpointComparison) -> str:
    if not comparison.changes:
        return "No meaningful development changes."
    lines = [f"{comparison.left_id} → {comparison.right_id}"]
    if comparison.unchanged_head_only:
        lines.append("Git HEAD changed, but no architecture/proof meaning changed.")
    for change in comparison.changes:
        marker = "PROOF" if change.significance == "PROOF_TRANSITION" else change.significance
        lines.append(f"[{marker}] {change.category}: {change.before} → {change.after}")
    return "\n".join(lines)
