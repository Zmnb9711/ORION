from __future__ import annotations

import asyncio
import json

from orion.yandex_realtime_informational_presenter import (
    RealtimeInformationalResult,
    YandexRealtimeTextConfig,
)
from tools.informational_presentation_benchmark import (
    BENCHMARK_CASES,
    BenchmarkSample,
    DiagnosticRejection,
    InformationalPresentationBenchmark,
    SemanticAdversarialSample,
    build_report,
    failure_distribution,
    promotion_gates,
    sanitize_diagnostic_formulation,
    semantic_promotion_gates,
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


def test_semantic_promotion_requires_safe_adversarial_and_total_latency() -> None:
    samples: list[BenchmarkSample] = []
    for case in BENCHMARK_CASES[:4]:
        for index in range(1, 21):
            sample = _sample("yandex_realtime_semantic", case.case_id, index, 600)
            sample.validation_latency_ms = 100
            sample.total_latency_ms = 700
            sample.session_reused = True
            samples.append(sample)
    adversarial = tuple(
        SemanticAdversarialSample(
            case_id=f"adversarial-{index}",
            expected_category="unrelated_fact",
            rejected=True,
            downstream_reached=False,
            latency_ms=100,
            error_code="semantic_judge_rejected",
        )
        for index in range(13)
    )
    gates, decision, failure_space = semantic_promotion_gates(
        samples,
        adversarial,
        required_warm_samples=20,
    )
    assert decision == "NUMERICAL_GO_ONLY"
    assert failure_space == "OPEN_ENDED"
    assert gates["unsafe_acceptance"]["result"] == "PASS"
    assert gates["invalid_downstream"]["result"] == "PASS"
    assert gates["warm_total_median"]["result"] == "PASS"

    unsafe = list(adversarial)
    unsafe[0] = SemanticAdversarialSample(
        case_id="unsafe",
        expected_category="fuel",
        rejected=False,
        downstream_reached=True,
        latency_ms=100,
        error_code=None,
    )
    unsafe_gates, unsafe_decision, _ = semantic_promotion_gates(
        samples,
        tuple(unsafe),
        required_warm_samples=20,
    )
    assert unsafe_decision == "NO_GO"
    assert unsafe_gates["unsafe_acceptance"]["result"] == "FAIL"


def test_diagnostic_sanitizer_is_bounded_and_redacts_credential_shapes() -> None:
    secret = "synthetic-secret-value"
    text = (
        "Самолёт {{aircraft_identity}}. "
        f"Authorization: Bearer-token api_key={secret} "
        + ("длинный " * 100)
    )
    sanitized = sanitize_diagnostic_formulation(text, secrets=(secret,))
    assert len(sanitized) == 400
    assert secret not in sanitized
    assert "authorization" not in sanitized.casefold()
    assert "api_key" not in sanitized.casefold()
    assert "{{aircraft_identity}}" in sanitized


class _RejectedShellPresenter:
    provider_id = "yandex.realtime.text"

    async def formulate(self, request):  # noqa: ANN001, ANN201
        return RealtimeInformationalResult(
            request_id=request.request_id,
            provider_response_id="response-safe",
            output_text=(
                "Текущий самолёт — {{aircraft_identity}}, топливо доступно."
            ),
            first_token_latency_ms=10,
            complete_latency_ms=20,
            session_reused=True,
        )

    def record_event(self, event: str, **metadata: object) -> None:
        del event, metadata


def test_opt_in_diagnostic_captures_only_rejected_synthetic_shell() -> None:
    benchmark = object.__new__(InformationalPresentationBenchmark)
    benchmark._realtime_config = YandexRealtimeTextConfig(
        api_key="synthetic-secret-value",
        folder_id="synthetic-folder",
    )
    benchmark._diagnostic_capture_limit = 2
    benchmark.diagnostic_rejections = []
    sample = asyncio.run(
        benchmark._realtime_diagnostic_sample(  # noqa: SLF001
            _RejectedShellPresenter(),  # type: ignore[arg-type]
            BENCHMARK_CASES[0],
            1,
            cold=False,
            connect_latency_ms=None,
        )
    )
    assert sample.provider_output_status == "completed"
    assert sample.validator_status == "fail"
    assert sample.downstream_reached is False
    assert sample.error_code == "unsupported_extra_claim"
    assert len(benchmark.diagnostic_rejections) == 1
    capture = benchmark.diagnostic_rejections[0]
    assert capture.marker_positions == (18,)
    assert capture.correlation_id
    assert capture.sanitized_output == (
        "Текущий самолёт — {{aircraft_identity}}, топливо доступно."
    )


def test_private_report_includes_opt_in_bounded_rejection_capture(tmp_path) -> None:  # noqa: ANN001
    capture = DiagnosticRejection(
        case_id="ru-fa18",
        language="ru-RU",
        sample_index=1,
        cold=False,
        validation_error_code="unsupported_extra_claim",
        marker_positions=(18,),
        sanitized_output="Текущий самолёт — {{aircraft_identity}}, топливо доступно.",
        correlation_id="safe-correlation",
        first_token_latency_ms=10,
        complete_formulation_ms=20,
        total_latency_ms=21,
    )
    report = build_report(
        [_sample("yandex_realtime_text", "ru-fa18", 1, 100)],
        warm_samples=20,
        session_ids={"safe-session-id"},
        diagnostic_rejections=(capture,),
        diagnostic_capture_enabled=True,
        selected_case_ids=("ru-fa18",),
    )
    json_path, _ = write_private_report(report, tmp_path)
    encoded = json_path.read_text(encoding="utf-8")
    assert report["diagnostic"]["capture_enabled"] is True
    assert len(report["diagnostic"]["rejected_formulations"]) == 1
    assert "safe-correlation" in encoded
    assert "authorization" not in encoded.casefold()
