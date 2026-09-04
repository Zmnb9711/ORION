from __future__ import annotations

from test_arch_guard_ag2 import _build  # type: ignore[import-not-found]
from test_arch_guard_ag3 import _request, _run  # type: ignore[import-not-found]

from tools.orion_arch_guard.canonical_seed import (
    CANONICAL_ROADMAP_STAGES,
    DO_NOT_REINVENT_RULES,
    GOLDEN_COMPONENTS,
    HISTORICAL_RECONNECT_ITEMS,
    RECOVERED_IDEAS,
    RETIREMENT_CANDIDATES,
    USER_VALUED_FORGOTTEN_IDEAS,
)
from tools.orion_arch_guard.graph import CapabilityGraph, GraphBuilder


def _ids(items: list[dict[str, object]]) -> set[str]:
    return {str(item["record_id"]) for item in items}


def test_canonical_registers_are_typed_complete_and_capability_retrievable(tmp_path) -> None:  # noqa: ANN001
    database, result = _build(tmp_path)
    graph = CapabilityGraph(database)
    try:
        all_records = graph.canonical_records()
        awacs = graph.canonical_context(("AWACS_GCI",), query="Implement AWACS")
        debrief = graph.canonical_context(("DEBRIEF",), query="Build debrief")
    finally:
        graph.close()

    assert result.canonical_records == len(all_records)
    assert len(GOLDEN_COMPONENTS) == 18
    assert len(DO_NOT_REINVENT_RULES) == 15
    assert len(RETIREMENT_CANDIDATES) == 8
    assert len(RECOVERED_IDEAS) == 20
    assert len(USER_VALUED_FORGOTTEN_IDEAS) == 10
    assert "U04" in _ids(awacs["recovered_unimplemented_ideas"])
    assert "U17" in _ids(debrief["recovered_unimplemented_ideas"])
    assert awacs["work_classification"] == "RECOVERED_IDEA_IMPLEMENTATION"
    assert debrief["work_classification"] == "RECOVERED_IDEA_IMPLEMENTATION"
    assert all(item["provenance"] for item in all_records)


def test_canonical_seed_is_idempotent_and_signature_detects_change(tmp_path) -> None:  # noqa: ANN001
    database, first = _build(tmp_path)
    builder = GraphBuilder(database)
    try:
        second = builder.build()
        signature = builder.connection.execute(
            "SELECT value FROM graph_metadata WHERE key='CANONICAL_INPUT_SIGNATURE'"
        ).fetchone()[0]
    finally:
        builder.close()
    assert second.reused is True
    assert first.canonical_records == second.canonical_records
    assert signature == first.input_signature


def test_three_layer_context_and_realtime_benchmark_are_preserved(tmp_path) -> None:  # noqa: ANN001
    database, _result = _build(tmp_path)
    graph = CapabilityGraph(database)
    try:
        context = graph.canonical_context(
            ("NATURAL_INFORMATIONAL_PRESENTATION", "YANDEX_REALTIME"),
            query="Adapt Realtime informational presentation",
        )
    finally:
        graph.close()
    assert context["current_best"]
    assert _ids(context["historical_best"]) == {"HR01"}
    candidate = context["historical_best"][0]
    assert candidate["metadata"]["benchmark_verdict"] == "BENCHMARK_NO_GO"
    assert candidate["metadata"]["successful_warm_median_ms"] == 357
    assert candidate["metadata"]["successful_warm_p90_ms"] == 515
    assert candidate["metadata"]["validator_accepted"] == "56/56"
    assert candidate["metadata"]["failure_rate_percent"] == 30
    assert context["work_classification"] == "HISTORICAL_ADAPTATION"
    assert context["actually_missing"] is False


def test_c3_position_preserves_historical_no_go_and_advances_only_to_c4() -> None:
    stages = {item.record_id: item for item in CANONICAL_ROADMAP_STAGES}
    assert stages["C1"].status == "COMPLETE"
    assert stages["C3"].status == "COMPLETE"
    assert stages["C3"].metadata["current_position"] is True
    assert stages["C4"].status == "APPROVED_NEXT_STEP"
    reconnect = next(item for item in HISTORICAL_RECONNECT_ITEMS if item.record_id == "HR01")
    assert reconnect.status == "RECONNECTED_ADAPTED_NON_DEFAULT"
    assert reconnect.metadata["benchmark_verdict"] == "BENCHMARK_NO_GO"
    assert reconnect.metadata["current_semantic_policy"] == "D75_CURRENT_CLARIFIED"


def test_retirement_conflict_is_semantic_and_not_plain_capability_match(tmp_path) -> None:  # noqa: ANN001
    database, _result = _build(tmp_path)
    graph = CapabilityGraph(database)
    try:
        inspect = graph.canonical_context(("STT",), query="Inspect current STT")
        restore = graph.canonical_context(("STT",), query="Restore Whisper fallback")
    finally:
        graph.close()
    assert inspect["retirement_candidates"]
    assert inspect["retirement_conflicts"] == []
    assert _ids(restore["retirement_conflicts"]) == {"RC05"}
    assert restore["work_classification"] == "RETIREMENT_CONFLICT"


def test_true_greenfield_requires_exhausted_canonical_search(tmp_path) -> None:  # noqa: ANN001
    database, _result = _build(tmp_path)
    graph = CapabilityGraph(database)
    try:
        for capability in ("UNMAPPED_ALPHA", "UNMAPPED_BETA", "UNMAPPED_GAMMA"):
            context = graph.canonical_context((capability,), query="new capability")
            assert context["work_classification"] == "TRUE_GREENFIELD"
            assert context["actually_missing"] is True
            assert context["search_order"][-1] == "TRUE_GREENFIELD"
    finally:
        graph.close()


def test_guard_surfaces_d74_and_capability_filtered_canonical_context(tmp_path) -> None:  # noqa: ANN001
    report, _database = _run(
        tmp_path,
        _request("Adapt Realtime informational presenter reliability"),
    )
    current = {item["decision_id"] for item in report.result["decisions"]["CURRENT"]}
    context = report.result["canonical_context"]
    assert "D74" in current
    assert context["work_classification"] == "HISTORICAL_ADAPTATION"
    assert _ids(context["historical_best"]) == {"HR01"}
    assert "Canonical context" in report.human_report


def test_guard_uses_complete_task_semantics_for_retirement_conflicts(tmp_path) -> None:  # noqa: ANN001
    restore_dir = tmp_path / "restore"
    restore_dir.mkdir()
    restore, _database = _run(
        restore_dir,
        _request(
            "Restore Whisper",
            proposed="No implementation; retrieve relevant history only.",
            capabilities=("STT",),
        ),
    )
    negated_dir = tmp_path / "negated"
    negated_dir.mkdir()
    negated, _database = _run(
        negated_dir,
        _request(
            "Inspect STT without restoring retired mechanisms",
            constraints=("Do not restore Whisper.",),
            capabilities=("STT",),
        ),
    )

    assert _ids(restore.result["canonical_context"]["retirement_conflicts"]) == {"RC05"}
    assert restore.result["canonical_context"]["work_classification"] == "RETIREMENT_CONFLICT"
    assert negated.result["canonical_context"]["retirement_conflicts"] == []


def test_guard_resolves_awacs_voice_interaction_without_explicit_capability(tmp_path) -> None:  # noqa: ANN001
    report, _database = _run(
        tmp_path,
        _request("Task Recall: AWACS voice interaction"),
    )

    capabilities = {
        item["capability_id"] for item in report.result["affected_capabilities"]
    }
    assert "AWACS_GCI" in capabilities
    assert "U04" in _ids(
        report.result["canonical_context"]["recovered_unimplemented_ideas"]
    )
    assert (
        report.result["canonical_context"]["work_classification"]
        == "RECOVERED_IDEA_IMPLEMENTATION"
    )
