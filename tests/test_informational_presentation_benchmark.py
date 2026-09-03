from __future__ import annotations

import json

from tools.informational_presentation_benchmark import (
    BENCHMARK_CASES,
    BenchmarkSample,
    build_report,
    failure_distribution,
    promotion_gates,
    summarize_samples,
    write_private_report,
)


def _sample(
    backend: str,
    case_id: str,
    index: int,
    latency_ms: float,
) -> BenchmarkSample:
    return BenchmarkSample(
        backend=backend,  # type: ignore[arg-type]
        case_id=case_id,
        sample_index=index,
        cold=False,
        success=True,
        provider_output_status="completed",
        validator_status="pass",
        identity_preserved=True,
        unsupported_claim_result="pass",
        downstream_reached=True,
        session_reused=(backend == "yandex_realtime_text"),
        connect_latency_ms=None,
        first_token_latency_ms=latency_ms / 2,
        complete_formulation_ms=latency_ms,
        validation_latency_ms=0.2,
        binding_latency_ms=0.1,
        total_latency_ms=latency_ms + 0.3,
        bound_final_text="bounded synthetic response",
        error_code=None,
    )


def test_promotion_gate_requires_complete_warm_matrix_and_paired_qwen_samples() -> None:
    samples: list[BenchmarkSample] = []
    for case in BENCHMARK_CASES[:4]:
        for index in range(1, 21):
            samples.append(_sample("qwen", case.case_id, index, 1_000))
            samples.append(
                _sample("yandex_realtime_text", case.case_id, index, 100)
            )
    gates, decision = promotion_gates(samples, required_warm_samples=20)
    assert decision == "BENCHMARK_GO"
    assert all(value["result"] == "PASS" for value in gates.values())
    assert gates["paired_median_improvement"]["actual"] == 90.0

    incomplete, incomplete_decision = promotion_gates(samples[:2], required_warm_samples=20)
    assert incomplete_decision == "BENCHMARK_INCOMPLETE"
    assert incomplete["warm_sample_count"]["result"] == "INCOMPLETE"


def test_summary_and_private_artifacts_are_bounded_and_credential_free(tmp_path) -> None:  # noqa: ANN001
    samples = [
        _sample("qwen", "ru-fa18", 1, 1_000),
        _sample("yandex_realtime_text", "ru-fa18", 1, 100),
    ]
    summaries = summarize_samples(samples)
    assert summaries["qwen:ru-fa18:warm"]["complete_median_ms"] == 1_000
    report = build_report(samples, warm_samples=20, session_ids={"safe-session-id"})
    json_path, markdown_path = write_private_report(report, tmp_path)
    encoded = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["benchmark_decision"] == (
        "BENCHMARK_INCOMPLETE"
    )
    assert report["realtime_candidate_decision"] == "REALTIME_CANDIDATE_INCOMPLETE"
    assert "api_key" not in encoded.casefold()
    assert "authorization" not in encoded.casefold()
    assert "provider reasoning" not in encoded.casefold()


def test_failure_distribution_preserves_safe_scalar_reason_without_provider_text() -> None:
    failed = _sample("yandex_realtime_text", "ru-fa18", 1, 100)
    failed.success = False
    failed.validator_status = "fail"
    failed.downstream_reached = False
    failed.bound_final_text = None
    failed.error_code = "unsupported_extra_claim"
    assert failure_distribution([failed]) == {
        "yandex_realtime_text:ru-fa18:warm:unsupported_extra_claim": 1
    }


def test_validation_rejection_is_not_misclassified_as_realtime_protocol_failure() -> None:
    samples: list[BenchmarkSample] = []
    for case in BENCHMARK_CASES[:4]:
        for index in range(1, 21):
            sample = _sample("yandex_realtime_text", case.case_id, index, 100)
            if case.case_id == "ru-fa18" and index <= 5:
                sample.success = False
                sample.validator_status = "fail"
                sample.downstream_reached = False
                sample.error_code = "unsupported_extra_claim"
            samples.append(sample)
    gates, decision = promotion_gates(samples, required_warm_samples=20)
    assert decision == "BENCHMARK_NO_GO"
    assert gates["failure_timeout_rate"]["result"] == "FAIL"
    assert gates["realtime_protocol_execution"]["result"] == "PASS"
