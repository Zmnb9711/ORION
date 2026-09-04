from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.orion_arch_guard.fingerprints import canonical_sha256
from tools.orion_development_console.comparison import compare_checkpoints, render_comparison
from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.memory import AmbiguousTaskRecall, DevelopmentMemoryService
from tools.orion_development_console.memory_models import DevelopmentCheckpoint, PromptRecord, PromptType
from tools.orion_development_console.memory_store import CheckpointStore, PromptStore
from tools.orion_development_console.models import (
    TruthDomain,
    VerificationObservation,
    VerificationReport,
    VerificationState,
)
from tools.orion_development_console.privacy import sanitize
from tools.orion_development_console.store import VerificationReportStore
from tools.orion_development_console.theme import PALETTE, status_group


NOW = datetime(2026, 9, 2, 18, 0, tzinfo=UTC)
HEAD = "a" * 40
GUARD_ID = "AG-20260902-180000-deadbeef-aaaaaaa-r1"


def _checkpoint(identifier: str, **updates: object) -> DevelopmentCheckpoint:
    values = {
        "checkpoint_id": identifier,
        "created_at": "2026-09-02T18:00:00+00:00",
        "branch": "dev/test",
        "head_sha": HEAD,
        "guard_report_id": GUARD_ID,
        "verification_report_id": "OV-1",
        "development_stage": "PHASE 2",
        "approved_next_step": "PHASE 3",
        "current_decisions": ["D71", "D73"],
        "completed_work": ["console"],
        "field_proven": [],
        "probe_or_automated_proven": ["console"],
        "implementations": ["DEVELOPMENT_CONSOLE"],
        "previous_best_mechanisms": ["GUARD"],
        "do_not_rebuild": ["Phase 1"],
        "do_not_reinvent": ["Guard retrieval"],
        "recent_evidence": [{"id": "E1"}],
        "provenance": ["guard:" + GUARD_ID],
        "content_fingerprint": "",
    }
    values.update(updates)
    record = DevelopmentCheckpoint.model_validate(values)
    return record.model_copy(update={"content_fingerprint": record.expected_fingerprint()})


def _prompt(identifier: str, content: str = "complete visible prompt") -> PromptRecord:
    record = PromptRecord(
        prompt_id=identifier,
        prompt_type=PromptType.FULL_RECALL,
        created_at="2026-09-02T18:00:00+00:00",
        guard_report_id=GUARD_ID,
        verification_report_id="OV-1",
        head_sha=HEAD,
        content=content,
        content_fingerprint="",
    )
    return record.model_copy(update={"content_fingerprint": record.expected_fingerprint()})


def _guard() -> dict[str, object]:
    return {
        "report_id": GUARD_ID,
        "head_sha": HEAD,
        "gate": "PASS",
        "history_coverage": {"overall": "COMPLETE", "architecture_critical_missing": []},
        "affected_capabilities": [{"capability_id": "ARCHITECTURE_GOVERNANCE"}],
        "decisions": {
            "CURRENT": [{"decision_id": "D71"}, {"decision_id": "D73"}, {"decision_id": "D74"}],
            "SUPERSEDED": [{"decision_id": "D30"}],
            "REJECTED": [{"decision_id": "D15"}],
        },
        "implementations": {
            "CURRENT": ["DEVELOPMENT_CONSOLE"],
            "FIELD_PROVEN": ["PERSISTENT_ATC"],
            "PROBE": ["CONSOLE_PROBE"],
        },
        "previous_best": {
            "previous_implementations_found": ["PROJECT_MEMORY"],
            "previous_best_mechanisms": ["GUARD_INDEX"],
        },
        "evidence_reuse": {"evidence_remains_valid": True},
        "conflicts": [],
        "requires_user_decision": False,
        "canonical_context": {
            "strategy": [{"record_id": "STRATEGY_A_CURRENT_RECONNECT"}],
            "current_best": [{"record_id": "GC01"}, {"record_id": "GC18"}],
            "historical_best": [{"record_id": "HR01"}],
            "recovered_unimplemented_ideas": [{"record_id": "U04"}, {"record_id": "U17"}],
            "user_valued_forgotten_ideas": [{"record_id": "UV02"}],
            "do_not_reinvent": [{"record_id": "DNR11"}],
            "retirement_candidates": [{"record_id": "RC05"}],
            "retirement_conflicts": [],
            "work_classification": "CURRENT_EXTENSION",
            "actually_missing": False,
            "input_signature": "CANONICAL-FIXTURE",
        },
    }


def _context(tmp_path: Path) -> VerificationContext:
    guard_root = tmp_path / "guard"
    reports = guard_root / "reports"
    reports.mkdir(parents=True)
    (reports / f"{GUARD_ID}.json").write_text(json.dumps(_guard()), encoding="utf-8")

    def git_runner(_root: Path, arguments: tuple[str, ...]) -> str:
        values = {
            ("rev-parse", "HEAD"): HEAD,
            ("branch", "--show-current"): "dev/test",
            ("rev-list", "--count", "HEAD"): "12",
            ("status", "--porcelain=v1"): "",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/dev/test",
            ("rev-parse", "@{upstream}"): HEAD,
            ("rev-list", "--left-right", "--count", "HEAD...@{upstream}"): "0 0",
        }
        return values[arguments]

    return VerificationContext(
        repository_root=tmp_path / "repo",
        local_app_data=tmp_path,
        guard_root=guard_root,
        console_root=tmp_path / "console",
        architecture_report_id=GUARD_ID,
        git_runner=git_runner,
        now=lambda: NOW,
    )


def _service(tmp_path: Path, task_guard=None) -> DevelopmentMemoryService:  # noqa: ANN001
    return DevelopmentMemoryService(_context(tmp_path), task_guard=task_guard, now=lambda: NOW)


def test_checkpoint_create_once_and_atomic_save(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    record = _checkpoint("CP-1")
    path = store.save_create_once(record)
    assert path.is_file()
    assert not list(path.parent.glob("*.tmp"))
    with pytest.raises(FileExistsError):
        store.save_create_once(record)


def test_checkpoint_fingerprint_validation_detects_tampering(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    path = store.save_create_once(_checkpoint("CP-1"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["development_stage"] = "TAMPERED"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        store.load("CP-1")


def test_schema_one_checkpoint_remains_readable_after_canonical_fields_are_added(
    tmp_path: Path,
) -> None:
    store = CheckpointStore(tmp_path)
    record = _checkpoint("CP-LEGACY")
    payload = record.model_dump(mode="json")
    payload["schema_version"] = 1
    for field in (
        "canonical_strategy",
        "canonical_baseline_sha",
        "d74_status",
        "canonical_status",
        "golden_components",
        "historical_reconnect_items",
        "recovered_ideas",
        "retirement_candidates",
        "canonical_input_signature",
        "realtime_candidate",
    ):
        payload.pop(field)
    payload["content_fingerprint"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "content_fingerprint"}
    ).casefold()
    store.root.mkdir(parents=True)
    store._record_path("CP-LEGACY").write_text(  # noqa: SLF001
        json.dumps(payload), encoding="utf-8"
    )

    loaded = store.load("CP-LEGACY")

    assert loaded.schema_version == 1
    assert loaded.canonical_status == "NOT_RECORDED"
    assert loaded.golden_components == []


def test_checkpoint_preview_candidate_is_not_saved(tmp_path: Path) -> None:
    service = _service(tmp_path)
    candidate = service.build_checkpoint_candidate(
        development_stage="PHASE 2", approved_next_step="PHASE 3"
    )
    assert candidate.checkpoint_id.startswith("CP-")
    assert service.checkpoints.list_records() == []
    service.save_checkpoint(candidate)
    assert service.checkpoints.latest() == candidate


def test_checkpoint_provenance_uses_actual_saved_verification_report(tmp_path: Path) -> None:
    context = _context(tmp_path)
    verification = VerificationReport(
        verification_id="OV-20260902-180000-aaaaaaa-deadbeef",
        generated_at=NOW.isoformat(),
        repository_head=HEAD,
        architecture_guard_report_id=GUARD_ID,
        architecture_guard_gate="PASS",
        observations=[
            VerificationObservation(
                subject="evidence",
                truth_domain=TruthDomain.MACHINE,
                state=VerificationState.VERIFIED,
                verified_at=NOW.isoformat(),
                verification_method="bounded metadata scan",
                details={
                    "evidence_zip_count": 3,
                    "latest_evidence_timestamp": NOW.isoformat(),
                    "latest_evidence_build_sha": HEAD,
                },
            )
        ],
        actions_not_performed=["No product process was launched"],
    )
    VerificationReportStore(context.console_root).save(verification)
    checkpoint = DevelopmentMemoryService(context, now=lambda: NOW).build_checkpoint_candidate(
        development_stage="PHASE 2", approved_next_step="PHASE 3"
    )
    assert checkpoint.verification_report_id == verification.verification_id
    assert f"verification:{verification.verification_id}" in checkpoint.provenance
    assert checkpoint.recent_evidence[0]["verification_report_id"] == verification.verification_id


def test_missing_development_stage_requires_user_input(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit user input"):
        _service(tmp_path).build_checkpoint_candidate(
            development_stage="", approved_next_step=None
        )


def test_history_ordering_and_checkpoint_open(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    older = _checkpoint("CP-OLD")
    newer = _checkpoint("CP-NEW", created_at="2026-09-02T19:00:00+00:00")
    store.save_create_once(newer)
    store.save_create_once(older)
    assert [item.checkpoint_id for item in store.list_records()] == ["CP-OLD", "CP-NEW"]
    assert store.load("CP-OLD").development_stage == "PHASE 2"


def test_derived_checkpoint_index_is_rebuildable(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.save_create_once(_checkpoint("CP-1"))
    store.index_path.unlink()
    store.rebuild_index()
    assert json.loads(store.index_path.read_text(encoding="utf-8"))["records"][0]["id"] == "CP-1"


def test_compare_two_checkpoints_promotes_proof_transition() -> None:
    left = _checkpoint("CP-1", probe_or_automated_proven=["console"], field_proven=[])
    right = _checkpoint("CP-2", probe_or_automated_proven=[], field_proven=["console"])
    result = compare_checkpoints(left, right)
    assert any(item.significance == "PROOF_TRANSITION" for item in result.changes)
    assert "AUTOMATED_OR_PROBE_PROVEN → FIELD_PROVEN" in render_comparison(result)


def test_compare_current_head_only_is_low_noise() -> None:
    left = _checkpoint("CP-1")
    right = _checkpoint("CURRENT", head_sha="b" * 40)
    result = compare_checkpoints(left, right)
    assert result.unchanged_head_only
    assert "no architecture/proof meaning changed" in render_comparison(result)


def test_prompt_create_once_history_and_full_content(tmp_path: Path) -> None:
    store = PromptStore(tmp_path)
    prompt = _prompt("PR-1", "line one\nline two\nline three")
    store.save_create_once(prompt)
    assert store.load("PR-1").content == prompt.content
    assert store.latest() == prompt
    with pytest.raises(FileExistsError):
        store.save_create_once(prompt)


def test_full_recall_is_bounded_and_contains_provenance(tmp_path: Path) -> None:
    service = _service(tmp_path)
    record = service.generate_full_recall()
    assert record.prompt_type is PromptType.FULL_RECALL
    assert GUARD_ID in record.content
    assert "D71" in record.content
    assert "DO NOT REBUILD" in record.content
    assert "STRATEGY_A_CURRENT_RECONNECT" in record.content
    assert "IPB-20260903-171624" in record.content
    assert "full private L0 body sentinel" not in record.content
    assert service.prompts.latest() == record


def test_task_recall_uses_guard_capabilities(tmp_path: Path) -> None:
    def task_guard(_task: str, _head: str) -> dict[str, object]:
        result = _guard()
        result["affected_capabilities"] = [
            {"capability_id": "TOWER"},
            {"capability_id": "DEPARTURE"},
            {"capability_id": "ATC_HANDOFF"},
        ]
        return result

    record = _service(tmp_path, task_guard).generate_task_recall("Tower to Departure")
    assert record.capabilities == ["ATC_HANDOFF", "DEPARTURE", "TOWER"]
    assert "AG-2/AG-3" in record.content
    assert "Canonical work classification" in record.content


def test_checkpoint_candidate_contains_canonical_state_without_saving(tmp_path: Path) -> None:
    service = _service(tmp_path)
    candidate = service.build_checkpoint_candidate(
        development_stage="CANONICAL ORION BASELINE ESTABLISHED",
        approved_next_step="REALTIME INFORMATIONAL PRESENTER RELIABILITY CORRECTION",
    )
    assert candidate.canonical_strategy == "STRATEGY_A_CURRENT_RECONNECT"
    assert candidate.canonical_status == "READY_FOR_USER_SAVE"
    assert candidate.canonical_baseline_sha == HEAD
    assert candidate.d74_status == "CURRENT"
    assert candidate.golden_components == ["GC01", "GC18"]
    assert candidate.historical_reconnect_items == ["HR01"]
    assert candidate.recovered_ideas == ["U04", "U17"]
    assert candidate.canonical_input_signature == "CANONICAL-FIXTURE"
    assert candidate.realtime_candidate == (
        "C3_AUTOMATED_PROVEN / KEEP / NON_DEFAULT / C4_FIELD_PROOF_REQUIRED"
    )
    assert service.checkpoints.list_records() == []


@pytest.mark.parametrize(
    "guard_update",
    [
        {"affected_capabilities": []},
        {"requires_user_decision": True, "candidate_capabilities": [{"capability_id": "TOWER"}]},
    ],
)
def test_ambiguous_task_recall_requires_clarification(
    tmp_path: Path, guard_update: dict[str, object]
) -> None:
    def task_guard(_task: str, _head: str) -> dict[str, object]:
        result = _guard()
        result.update(guard_update)
        return result

    with pytest.raises(AmbiguousTaskRecall):
        _service(tmp_path, task_guard).generate_task_recall("something ambiguous")


def test_continue_requires_latest_checkpoint(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No explicitly saved checkpoint"):
        _service(tmp_path).generate_continue()


def test_continue_requires_approved_next_step(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save_checkpoint(
        service.build_checkpoint_candidate(
            development_stage="PHASE 2", approved_next_step=None
        )
    )
    with pytest.raises(ValueError, match="Approved Next Step"):
        service.generate_continue()


def test_continue_includes_checkpoint_guard_ov_and_diff(tmp_path: Path) -> None:
    service = _service(tmp_path)
    checkpoint = service.build_checkpoint_candidate(
        development_stage="PHASE 2", approved_next_step="PHASE 3"
    )
    service.save_checkpoint(checkpoint)
    prompt = service.generate_continue()
    assert checkpoint.checkpoint_id in prompt.content
    assert GUARD_ID in prompt.content
    assert "Meaningful change since checkpoint" in prompt.content
    assert "Approved next step: PHASE 3" in prompt.content


def test_checkpoint_recovery_prompt_retains_historical_authority_warning(tmp_path: Path) -> None:
    service = _service(tmp_path)
    prompt = service.checkpoint_recovery_prompt(_checkpoint("CP-1"))
    assert "historical truth only" in prompt.content
    assert "Re-verify current Git" in prompt.content


def test_regeneration_creates_new_prompt_record(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.generate_full_recall()
    second = service.regenerate_prompt(first)
    assert first.prompt_id != second.prompt_id
    assert len(service.prompts.list_records()) == 2


def test_private_storage_stays_below_console_root(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.generate_full_recall()
    assert service.prompts.root.parent == service.context.console_root
    assert "prompts" in service.prompts.root.parts


def test_secret_sanitization_applies_to_checkpoint_evidence() -> None:
    assert sanitize({"api_token": "secret", "safe": "value"}) == {
        "api_token": "<redacted>",
        "safe": "value",
    }


def test_launcher_family_theme_adapter_has_exact_identity_tokens() -> None:
    assert PALETTE["background"] == "#070b10"
    assert PALETTE["cyan"] == "#4ac6d7"
    assert status_group("FIELD_PROVEN") == "GOOD"
    assert status_group("NOT_CHECKED") == "UNKNOWN"


def test_theme_and_memory_do_not_import_launcher_or_core() -> None:
    root = Path(__file__).parents[1] / "tools" / "orion_development_console"
    source = (root / "theme.py").read_text(encoding="utf-8") + (root / "memory.py").read_text(encoding="utf-8")
    assert "desktop_launcher" not in source
    assert "core_process" not in source
