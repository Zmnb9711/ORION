"""Private isolated A/B benchmark for ORION informational formulation backends."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from orion.aircraft_identity_query import (
    AircraftIdentityFormulationError,
    AircraftIdentityFormulationService,
    AircraftIdentityQueryResult,
    AircraftIdentityQueryStatus,
    AircraftIdentityRealtimeCandidateService,
)
from orion.aircraft_identity_presentation import (
    AircraftIdentityShellValidationError,
    aircraft_identity_marker,
    bind_aircraft_identity_shell,
    validate_aircraft_identity_shell,
)
from orion.world_model_contracts import (
    WorldFactAuthority,
    WorldFactSource,
    WorldFactStatus,
)
from orion.yandex_qwen_planner import (
    QWEN_MODEL_ID,
    YandexQwenPlannerConfig,
    YandexQwenPlannerProvider,
    load_yandex_qwen_planner_config,
)
from orion.yandex_realtime_informational_presenter import (
    InformationalPresenterError,
    RealtimeInformationalRequest,
    YandexRealtimeInformationalPresenter,
    YandexRealtimeTextConfig,
)
from orion.yandex_realtime_provider import YANDEX_MODEL, YANDEX_REALTIME_ENDPOINT


Backend = Literal["qwen", "yandex_realtime_text"]


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    language: Literal["ru-RU", "en-US"]
    raw_aircraft_id: str | None
    display_name: str | None

    @property
    def unavailable(self) -> bool:
        return self.raw_aircraft_id is None

    @property
    def utterance(self) -> str:
        return (
            "В каком самолёте я нахожусь?"
            if self.language == "ru-RU"
            else "What aircraft am I in?"
        )

    def result(self) -> AircraftIdentityQueryResult:
        return AircraftIdentityQueryResult(
            status=(
                AircraftIdentityQueryStatus.UNAVAILABLE
                if self.unavailable
                else AircraftIdentityQueryStatus.AVAILABLE
            ),
            raw_aircraft_id=self.raw_aircraft_id,
            display_name=self.display_name,
            fact_status=(
                WorldFactStatus.UNAVAILABLE
                if self.unavailable
                else WorldFactStatus.KNOWN
            ),
            source=WorldFactSource.DCS_EXPORT,
            authority=WorldFactAuthority.AUTHORITATIVE,
            observed_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
            age_seconds=1,
            generation=f"benchmark:{self.case_id}",
            unavailable_reason=("source_not_connected" if self.unavailable else None),
        )


BENCHMARK_CASES = (
    BenchmarkCase("ru-fa18", "ru-RU", "FA-18C_hornet", "F/A-18C Hornet"),
    BenchmarkCase("ru-f5", "ru-RU", "F-5E-3", "F-5E-3 Tiger II"),
    BenchmarkCase("en-fa18", "en-US", "FA-18C_hornet", "F/A-18C Hornet"),
    BenchmarkCase("en-f5", "en-US", "F-5E-3", "F-5E-3 Tiger II"),
    BenchmarkCase("ru-unavailable", "ru-RU", None, None),
)


@dataclass(slots=True)
class BenchmarkSample:
    backend: Backend
    case_id: str
    sample_index: int
    cold: bool
    success: bool
    provider_output_status: str
    validator_status: str
    identity_preserved: bool
    unsupported_claim_result: str
    downstream_reached: bool
    session_reused: bool | None
    connect_latency_ms: float | None
    first_token_latency_ms: float | None
    complete_formulation_ms: float | None
    validation_latency_ms: float | None
    binding_latency_ms: float | None
    total_latency_ms: float
    bound_final_text: str | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticRejection:
    case_id: str
    language: str
    sample_index: int
    cold: bool
    validation_error_code: str
    marker_positions: tuple[int, ...]
    sanitized_output: str
    correlation_id: str
    first_token_latency_ms: float
    complete_formulation_ms: float
    total_latency_ms: float


_DIAGNOSTIC_OUTPUT_LIMIT = 400


def sanitize_diagnostic_formulation(
    value: str,
    *,
    secrets: tuple[str, ...] = (),
) -> str:
    """Keep one bounded synthetic shell while removing credential-shaped text."""

    sanitized = " ".join(value.split())
    for secret in secrets:
        if len(secret) >= 8:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = re.sub(
        r"(?i)\b(?:authorization|api[-_ ]?key)\b\s*[:=]\s*\S+",
        "[REDACTED]",
        sanitized,
    )
    sanitized = re.sub(r"(?i)\bbearer\s+\S+", "[REDACTED]", sanitized)
    return sanitized[:_DIAGNOSTIC_OUTPUT_LIMIT]


class _StaticQuery:
    def __init__(self, result: AircraftIdentityQueryResult) -> None:
        self._result = result

    def resolve(self) -> AircraftIdentityQueryResult:
        return self._result


def _identity_preserved(case: BenchmarkCase, text: str) -> bool:
    if case.display_name is not None:
        return text.count(case.display_name) == 1
    unavailable = (
        "данные о текущем самолёте из DCS недоступны"
        if case.language == "ru-RU"
        else "current aircraft identity from DCS is unavailable"
    )
    return unavailable in text


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def summarize_samples(samples: list[BenchmarkSample]) -> dict[str, dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    keys = sorted({(item.backend, item.case_id, item.cold) for item in samples})
    for backend, case_id, cold in keys:
        group = [
            item
            for item in samples
            if item.backend == backend and item.case_id == case_id and item.cold == cold
        ]
        successes = [item for item in group if item.success]
        first = [item.first_token_latency_ms for item in successes if item.first_token_latency_ms is not None]
        complete = [
            item.complete_formulation_ms
            for item in successes
            if item.complete_formulation_ms is not None
        ]
        validation = [
            item.validation_latency_ms
            for item in successes
            if item.validation_latency_ms is not None
        ]
        binding = [
            item.binding_latency_ms
            for item in successes
            if item.binding_latency_ms is not None
        ]
        summaries[f"{backend}:{case_id}:{'cold' if cold else 'warm'}"] = {
            "sample_count": len(group),
            "success_count": len(successes),
            "validation_failures": sum(item.validator_status == "fail" for item in group),
            "timeouts": sum(
                item.error_code
                in {"request_timeout", "provider_timeout", "deadline_exceeded"}
                for item in group
            ),
            "other_failures": sum(
                not item.success and item.error_code != "request_timeout" for item in group
            ),
            "first_token_median_ms": round(statistics.median(first), 3) if first else None,
            "first_token_p90_ms": _percentile(first, 0.9),
            "complete_median_ms": round(statistics.median(complete), 3) if complete else None,
            "complete_p90_ms": _percentile(complete, 0.9),
            "validation_median_ms": (
                round(statistics.median(validation), 3) if validation else None
            ),
            "binding_median_ms": round(statistics.median(binding), 3) if binding else None,
            "session_reuse_rate": (
                round(
                    sum(item.session_reused is True for item in successes) / len(successes),
                    4,
                )
                if successes
                else None
            ),
        }
    return summaries


def failure_distribution(samples: list[BenchmarkSample]) -> dict[str, int]:
    failures: dict[str, int] = {}
    for item in samples:
        if item.success:
            continue
        key = ":".join(
            (
                item.backend,
                item.case_id,
                "cold" if item.cold else "warm",
                item.error_code or "unclassified",
            )
        )
        failures[key] = failures.get(key, 0) + 1
    return dict(sorted(failures.items()))


def promotion_gates(
    samples: list[BenchmarkSample],
    *,
    required_warm_samples: int,
) -> tuple[dict[str, dict[str, object]], str]:
    warm_realtime = [
        item for item in samples if item.backend == "yandex_realtime_text" and not item.cold
    ]
    primary_cases = {case.case_id for case in BENCHMARK_CASES[:4]}
    primary = [item for item in warm_realtime if item.case_id in primary_cases]
    successful = [item for item in primary if item.success]
    session_established = any(
        item.provider_output_status != "connect_failed"
        for item in samples
        if item.backend == "yandex_realtime_text"
    )
    protocol_error_codes = {
        "cancelled",
        "provider_error",
        "protocol_error",
        "request_timeout",
        "session_busy",
        "session_unavailable",
    }
    substantive_failures = [
        item
        for item in primary
        if not item.success
        and (
            item.provider_output_status == "connect_failed"
            or item.error_code in protocol_error_codes
        )
    ]
    complete_values = [
        item.complete_formulation_ms
        for item in successful
        if item.complete_formulation_ms is not None
    ]
    per_case_counts = {
        case_id: sum(item.case_id == case_id for item in primary)
        for case_id in sorted(primary_cases)
    }
    sample_complete = all(
        count >= required_warm_samples for count in per_case_counts.values()
    )
    validation_ok = bool(successful) and all(
        item.validator_status == "pass" and item.identity_preserved for item in successful
    )
    downstream_ok = all(
        not item.downstream_reached or item.success for item in warm_realtime
    )
    failure_rate = (
        sum(not item.success for item in primary) / len(primary) if primary else 1.0
    )
    median_complete = statistics.median(complete_values) if complete_values else None
    p90_complete = _percentile(complete_values, 0.9)

    paired_improvements: list[float] = []
    qwen_by_key = {
        (item.case_id, item.sample_index): item
        for item in samples
        if item.backend == "qwen" and not item.cold and item.success
    }
    for realtime in successful:
        qwen = qwen_by_key.get((realtime.case_id, realtime.sample_index))
        baseline_ms = qwen.complete_formulation_ms if qwen is not None else None
        if baseline_ms is None:
            baseline_ms = (
                17_233.8 if "fa18" in realtime.case_id else 14_516.5
            )
        if baseline_ms and realtime.complete_formulation_ms is not None:
            paired_improvements.append(
                1 - realtime.complete_formulation_ms / baseline_ms
            )
    required_pairs = required_warm_samples * len(primary_cases)
    pair_complete = len(paired_improvements) >= required_pairs
    paired_median = (
        statistics.median(paired_improvements) * 100 if paired_improvements else None
    )

    def gate(value: bool | None, actual: object, target: str) -> dict[str, object]:
        return {
            "result": "INCOMPLETE" if value is None else ("PASS" if value else "FAIL"),
            "actual": actual,
            "target": target,
        }

    gates = {
        "warm_sample_count": gate(
            True if sample_complete else None,
            per_case_counts,
            f">={required_warm_samples} per primary combination",
        ),
        "fact_marker_validation": gate(
            validation_ok if successful else None,
            f"{sum(item.validator_status == 'pass' for item in successful)}/{len(successful)}",
            "100% accepted samples",
        ),
        "invalid_downstream": gate(
            downstream_ok,
            sum(item.downstream_reached and not item.success for item in warm_realtime),
            "0",
        ),
        "warm_complete_median": gate(
            median_complete <= 1_500
            if median_complete is not None and sample_complete and session_established
            else None,
            round(median_complete, 3) if median_complete is not None else None,
            "<=1500 ms",
        ),
        "warm_complete_p90": gate(
            p90_complete <= 3_000
            if p90_complete is not None and sample_complete and session_established
            else None,
            p90_complete,
            "<=3000 ms",
        ),
        "paired_median_improvement": gate(
            paired_median >= 70 if paired_median is not None and pair_complete else None,
            round(paired_median, 3) if paired_median is not None else None,
            ">=70%",
        ),
        "failure_timeout_rate": gate(
            failure_rate <= 0.05 if sample_complete and session_established else None,
            round(failure_rate * 100, 3),
            "<=5%",
        ),
        "realtime_protocol_execution": gate(
            None
            if not session_established
            else (False if substantive_failures else True),
            (
                "no_session_established"
                if not session_established
                else f"substantive_failures={len(substantive_failures)}"
            ),
            "at least one current Realtime session and no protocol failures",
        ),
    }
    results = {str(value["result"]) for value in gates.values()}
    decision = (
        "BENCHMARK_NO_GO"
        if "FAIL" in results
        else ("BENCHMARK_INCOMPLETE" if "INCOMPLETE" in results else "BENCHMARK_GO")
    )
    return gates, decision


class InformationalPresentationBenchmark:
    def __init__(
        self,
        *,
        qwen_config: YandexQwenPlannerConfig,
        realtime_config: YandexRealtimeTextConfig,
        capture_rejected_shells: bool = False,
        diagnostic_capture_limit: int = 20,
    ) -> None:
        self._qwen_config = qwen_config
        self._realtime_config = realtime_config
        self._capture_rejected_shells = capture_rejected_shells
        self._diagnostic_capture_limit = diagnostic_capture_limit
        self.session_ids: set[str] = set()
        self.diagnostic_rejections: list[DiagnosticRejection] = []

    async def _qwen_sample(
        self,
        case: BenchmarkCase,
        sample_index: int,
    ) -> BenchmarkSample:
        started = time.perf_counter()
        try:
            service = AircraftIdentityFormulationService(query=_StaticQuery(case.result()))
            provider = YandexQwenPlannerProvider(self._qwen_config)
            outcome = await asyncio.to_thread(
                service.execute,
                provider=provider,
                interaction_id=uuid4(),
                utterance=case.utterance,
                language=case.language,
                deadline=datetime.now(UTC) + timedelta(seconds=60),
            )
            preserved = _identity_preserved(case, outcome.final_text)
            return BenchmarkSample(
                backend="qwen",
                case_id=case.case_id,
                sample_index=sample_index,
                cold=False,
                success=preserved,
                provider_output_status="completed",
                validator_status="pass" if preserved else "fail",
                identity_preserved=preserved,
                unsupported_claim_result="pass" if preserved else "fail",
                downstream_reached=preserved,
                session_reused=None,
                connect_latency_ms=None,
                first_token_latency_ms=None,
                complete_formulation_ms=outcome.qwen_latency_ms,
                validation_latency_ms=None,
                binding_latency_ms=None,
                total_latency_ms=(time.perf_counter() - started) * 1000,
                bound_final_text=outcome.final_text if preserved else None,
                error_code=None if preserved else "identity_mismatch",
            )
        except Exception as exc:
            error_code = type(exc).__name__
            if isinstance(exc, AircraftIdentityFormulationError):
                safe_message = str(exc)
                error_code = next(
                    (
                        code
                        for code in (
                            "deadline_exceeded",
                            "provider_timeout",
                            "provider_unavailable",
                            "invalid_final_response",
                        )
                        if code in safe_message
                    ),
                    "validation_failed",
                )
            return BenchmarkSample(
                backend="qwen",
                case_id=case.case_id,
                sample_index=sample_index,
                cold=False,
                success=False,
                provider_output_status="failed",
                validator_status="fail",
                identity_preserved=False,
                unsupported_claim_result="not_accepted",
                downstream_reached=False,
                session_reused=None,
                connect_latency_ms=None,
                first_token_latency_ms=None,
                complete_formulation_ms=None,
                validation_latency_ms=None,
                binding_latency_ms=None,
                total_latency_ms=(time.perf_counter() - started) * 1000,
                bound_final_text=None,
                error_code=error_code,
            )

    async def _realtime_sample(
        self,
        presenter: YandexRealtimeInformationalPresenter,
        case: BenchmarkCase,
        sample_index: int,
        *,
        cold: bool,
        connect_latency_ms: float | None,
    ) -> BenchmarkSample:
        if self._capture_rejected_shells:
            return await self._realtime_diagnostic_sample(
                presenter,
                case,
                sample_index,
                cold=cold,
                connect_latency_ms=connect_latency_ms,
            )
        started = time.perf_counter()
        try:
            service = AircraftIdentityRealtimeCandidateService(query=_StaticQuery(case.result()))
            outcome = await service.execute(
                presenter=presenter,
                interaction_id=uuid4(),
                language=case.language,
            )
            preserved = _identity_preserved(case, outcome.final_text)
            return BenchmarkSample(
                backend="yandex_realtime_text",
                case_id=case.case_id,
                sample_index=sample_index,
                cold=cold,
                success=preserved,
                provider_output_status="completed",
                validator_status="pass" if preserved else "fail",
                identity_preserved=preserved,
                unsupported_claim_result="pass" if preserved else "fail",
                downstream_reached=preserved,
                session_reused=outcome.session_reused,
                connect_latency_ms=connect_latency_ms,
                first_token_latency_ms=outcome.first_token_latency_ms,
                complete_formulation_ms=outcome.formulation_latency_ms,
                validation_latency_ms=outcome.validation_latency_ms,
                binding_latency_ms=outcome.binding_latency_ms,
                total_latency_ms=(time.perf_counter() - started) * 1000,
                bound_final_text=outcome.final_text if preserved else None,
                error_code=None if preserved else "identity_mismatch",
            )
        except Exception as exc:
            if isinstance(exc, InformationalPresenterError):
                code = exc.code.value
                validator_status = "not_run"
            elif isinstance(exc, AircraftIdentityShellValidationError) and exc.code:
                code = exc.code.value
                validator_status = "fail"
            else:
                code = type(exc).__name__
                validator_status = "fail"
            return BenchmarkSample(
                backend="yandex_realtime_text",
                case_id=case.case_id,
                sample_index=sample_index,
                cold=cold,
                success=False,
                provider_output_status="failed",
                validator_status=validator_status,
                identity_preserved=False,
                unsupported_claim_result="not_accepted",
                downstream_reached=False,
                session_reused=None,
                connect_latency_ms=connect_latency_ms,
                first_token_latency_ms=None,
                complete_formulation_ms=None,
                validation_latency_ms=None,
                binding_latency_ms=None,
                total_latency_ms=(time.perf_counter() - started) * 1000,
                bound_final_text=None,
                error_code=code,
            )

    async def _realtime_diagnostic_sample(
        self,
        presenter: YandexRealtimeInformationalPresenter,
        case: BenchmarkCase,
        sample_index: int,
        *,
        cold: bool,
        connect_latency_ms: float | None,
    ) -> BenchmarkSample:
        """Run the normal bounded contracts while retaining rejected synthetic shells."""

        started = time.perf_counter()
        interaction_id = uuid4()
        correlation_id = interaction_id.hex
        result = case.result()
        request = RealtimeInformationalRequest(
            request_id=correlation_id,
            semantic_meaning=result.semantic_meaning,
            language=case.language,
            required_marker=aircraft_identity_marker(result),
            fact_status=result.status.value,
            fact_source=result.source.value,
            fact_authority=result.authority.value,
            fact_generation=result.generation,
            freshness_status=result.fact_status.value,
        )
        try:
            presentation = await presenter.formulate(request)
            validation_started = time.perf_counter()
            try:
                validated_shell = validate_aircraft_identity_shell(
                    presentation.output_text,
                    result,
                    language=case.language,
                )
            except AircraftIdentityShellValidationError as exc:
                code = exc.code.value if exc.code else "validation_failed"
                presenter.record_event(
                    "formulation_failed",
                    correlation_id=correlation_id,
                    provider=presenter.provider_id,
                    error_type="validation_failed",
                )
                sanitized = sanitize_diagnostic_formulation(
                    presentation.output_text,
                    secrets=(self._realtime_config.api_key,),
                )
                marker = aircraft_identity_marker(result)
                if len(self.diagnostic_rejections) < self._diagnostic_capture_limit:
                    self.diagnostic_rejections.append(
                        DiagnosticRejection(
                            case_id=case.case_id,
                            language=case.language,
                            sample_index=sample_index,
                            cold=cold,
                            validation_error_code=code,
                            marker_positions=tuple(
                                match.start() for match in re.finditer(re.escape(marker), sanitized)
                            ),
                            sanitized_output=sanitized,
                            correlation_id=correlation_id,
                            first_token_latency_ms=presentation.first_token_latency_ms,
                            complete_formulation_ms=presentation.complete_latency_ms,
                            total_latency_ms=(time.perf_counter() - started) * 1000,
                        )
                    )
                return BenchmarkSample(
                    backend="yandex_realtime_text",
                    case_id=case.case_id,
                    sample_index=sample_index,
                    cold=cold,
                    success=False,
                    provider_output_status="completed",
                    validator_status="fail",
                    identity_preserved=False,
                    unsupported_claim_result="not_accepted",
                    downstream_reached=False,
                    session_reused=presentation.session_reused,
                    connect_latency_ms=connect_latency_ms,
                    first_token_latency_ms=presentation.first_token_latency_ms,
                    complete_formulation_ms=presentation.complete_latency_ms,
                    validation_latency_ms=(time.perf_counter() - validation_started) * 1000,
                    binding_latency_ms=None,
                    total_latency_ms=(time.perf_counter() - started) * 1000,
                    bound_final_text=None,
                    error_code=code,
                )
            validation_finished = time.perf_counter()
            binding_started = time.perf_counter()
            final_text = bind_aircraft_identity_shell(
                validated_shell,
                result,
                language=case.language,
            )
            binding_finished = time.perf_counter()
            preserved = _identity_preserved(case, final_text)
            return BenchmarkSample(
                backend="yandex_realtime_text",
                case_id=case.case_id,
                sample_index=sample_index,
                cold=cold,
                success=preserved,
                provider_output_status="completed",
                validator_status="pass" if preserved else "fail",
                identity_preserved=preserved,
                unsupported_claim_result="pass" if preserved else "fail",
                downstream_reached=preserved,
                session_reused=presentation.session_reused,
                connect_latency_ms=connect_latency_ms,
                first_token_latency_ms=presentation.first_token_latency_ms,
                complete_formulation_ms=presentation.complete_latency_ms,
                validation_latency_ms=(validation_finished - validation_started) * 1000,
                binding_latency_ms=(binding_finished - binding_started) * 1000,
                total_latency_ms=(time.perf_counter() - started) * 1000,
                bound_final_text=final_text if preserved else None,
                error_code=None if preserved else "identity_mismatch",
            )
        except InformationalPresenterError as exc:
            return BenchmarkSample(
                backend="yandex_realtime_text",
                case_id=case.case_id,
                sample_index=sample_index,
                cold=cold,
                success=False,
                provider_output_status="failed",
                validator_status="not_run",
                identity_preserved=False,
                unsupported_claim_result="not_run",
                downstream_reached=False,
                session_reused=None,
                connect_latency_ms=connect_latency_ms,
                first_token_latency_ms=None,
                complete_formulation_ms=None,
                validation_latency_ms=None,
                binding_latency_ms=None,
                total_latency_ms=(time.perf_counter() - started) * 1000,
                bound_final_text=None,
                error_code=exc.code.value,
            )

    async def run(
        self,
        *,
        warm_samples: int,
        qwen_samples: int,
        cases: tuple[BenchmarkCase, ...] = BENCHMARK_CASES,
    ) -> list[BenchmarkSample]:
        samples: list[BenchmarkSample] = []
        for case in cases:
            cold_presenter = YandexRealtimeInformationalPresenter(self._realtime_config)
            connect_started = time.perf_counter()
            try:
                await cold_presenter.connect()
                connect_ms = (time.perf_counter() - connect_started) * 1000
                if cold_presenter.session_id:
                    self.session_ids.add(cold_presenter.session_id)
                samples.append(
                    await self._realtime_sample(
                        cold_presenter,
                        case,
                        0,
                        cold=True,
                        connect_latency_ms=connect_ms,
                    )
                )
            except Exception as exc:
                samples.append(
                    BenchmarkSample(
                        backend="yandex_realtime_text",
                        case_id=case.case_id,
                        sample_index=0,
                        cold=True,
                        success=False,
                        provider_output_status="connect_failed",
                        validator_status="not_run",
                        identity_preserved=False,
                        unsupported_claim_result="not_run",
                        downstream_reached=False,
                        session_reused=False,
                        connect_latency_ms=(time.perf_counter() - connect_started) * 1000,
                        first_token_latency_ms=None,
                        complete_formulation_ms=None,
                        validation_latency_ms=None,
                        binding_latency_ms=None,
                        total_latency_ms=(time.perf_counter() - connect_started) * 1000,
                        bound_final_text=None,
                        error_code=(
                            exc.code.value
                            if isinstance(exc, InformationalPresenterError)
                            else type(exc).__name__
                        ),
                    )
                )
            finally:
                await cold_presenter.close()

            warm_presenter = YandexRealtimeInformationalPresenter(self._realtime_config)
            try:
                await warm_presenter.connect()
                if warm_presenter.session_id:
                    self.session_ids.add(warm_presenter.session_id)
                for index in range(1, warm_samples + 1):
                    sample = await self._realtime_sample(
                        warm_presenter,
                        case,
                        index,
                        cold=False,
                        connect_latency_ms=None,
                    )
                    samples.append(sample)
                    if not sample.success and warm_presenter.state.value != "ready":
                        break
            except Exception as exc:
                samples.append(
                    BenchmarkSample(
                        backend="yandex_realtime_text",
                        case_id=case.case_id,
                        sample_index=1,
                        cold=False,
                        success=False,
                        provider_output_status="connect_failed",
                        validator_status="not_run",
                        identity_preserved=False,
                        unsupported_claim_result="not_run",
                        downstream_reached=False,
                        session_reused=False,
                        connect_latency_ms=None,
                        first_token_latency_ms=None,
                        complete_formulation_ms=None,
                        validation_latency_ms=None,
                        binding_latency_ms=None,
                        total_latency_ms=0,
                        bound_final_text=None,
                        error_code=(
                            exc.code.value
                            if isinstance(exc, InformationalPresenterError)
                            else type(exc).__name__
                        ),
                    )
                )
            finally:
                await warm_presenter.close()

        for case in cases:
            for index in range(1, qwen_samples + 1):
                samples.append(await self._qwen_sample(case, index))
        return samples


def build_report(
    samples: list[BenchmarkSample],
    *,
    warm_samples: int,
    session_ids: set[str],
    diagnostic_rejections: tuple[DiagnosticRejection, ...] = (),
    diagnostic_capture_enabled: bool = False,
    selected_case_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    gates, decision = promotion_gates(samples, required_warm_samples=warm_samples)
    return {
        "schema_version": 1,
        "benchmark_id": f"IPB-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
        "created_at": datetime.now(UTC).isoformat(),
        "environment": {
            "dcs_started": False,
            "srs_started": False,
            "microphone_started": False,
            "speechkit_stt_called": False,
            "production_backend_changed": False,
        },
        "providers": {
            "qwen": {"provider": "yandex", "model": QWEN_MODEL_ID},
            "realtime": {
                "provider": "yandex",
                "model": YANDEX_MODEL,
                "endpoint": YANDEX_REALTIME_ENDPOINT,
                "session_ids": sorted(session_ids),
            },
        },
        "target_warm_samples_per_primary_combination": warm_samples,
        "selected_case_ids": list(selected_case_ids),
        "execution_note": (
            "Private synthetic rejected-shell diagnostic; no physical systems."
            if diagnostic_capture_enabled
            else "Isolated provider benchmark; no physical systems."
        ),
        "provider_call_counts": {
            "qwen": sum(item.backend == "qwen" for item in samples),
            "yandex_realtime_text": sum(
                item.backend == "yandex_realtime_text" for item in samples
            ),
        },
        "diagnostic": {
            "capture_enabled": diagnostic_capture_enabled,
            "privacy_boundary": (
                "bounded synthetic provider shell only; credentials, headers, prompts, "
                "conversation history and audio excluded"
            ),
            "rejected_formulations": [
                asdict(item) for item in diagnostic_rejections
            ],
        },
        "samples": [asdict(item) for item in samples],
        "summaries": summarize_samples(samples),
        "failure_distribution": failure_distribution(samples),
        "promotion_gates": gates,
        "benchmark_decision": decision,
        "realtime_candidate_decision": decision.replace(
            "BENCHMARK_", "REALTIME_CANDIDATE_"
        ),
        "comparison_hierarchy": {
            "primary": "historical physical Qwen field evidence",
            "secondary": "minimal same-harness Qwen smoke",
            "context": "Stage 6A/6A.1 with partial boundary comparability",
        },
        "historical_context": {
            "physical_qwen_fa18_ms": 17_233.8,
            "physical_qwen_f5_ms": 14_516.5,
            "stage6a_first_text_delta_median_ms": 101.5,
            "stage6a_first_audio_median_ms": 938,
            "stage6a_boundary_comparability": "PARTIAL",
        },
    }


def _human_summary(report: dict[str, Any]) -> str:
    lines = [
        "# ORION informational presentation A/B benchmark",
        "",
        f"Benchmark ID: `{report['benchmark_id']}`",
        f"Decision: **{report['benchmark_decision']}**",
        f"Realtime candidate: **{report['realtime_candidate_decision']}**",
        "",
        "## Execution scope",
        "",
        str(report.get("execution_note") or "Isolated provider benchmark; no physical systems."),
        "",
        "Provider calls:",
        "",
        "```json",
        json.dumps(report.get("provider_call_counts", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "Comparison hierarchy:",
        "",
        "```json",
        json.dumps(report["comparison_hierarchy"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Promotion gates",
        "",
        "| Criterion | Result | Actual | Target |",
        "|---|---|---|---|",
    ]
    for name, value in report["promotion_gates"].items():
        lines.append(
            f"| {name} | {value['result']} | `{value['actual']}` | {value['target']} |"
        )
    lines.extend(
        [
            "",
            "## Backend/combination summaries",
            "",
            "```json",
            json.dumps(report["summaries"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "Sensitive request material, full prompts and hidden model output are not recorded.",
            (
                "Bounded synthetic rejected-shell captures: "
                f"{len(report.get('diagnostic', {}).get('rejected_formulations', []))}."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def write_private_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = str(report["benchmark_id"])
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown_path.write_text(_human_summary(report), encoding="utf-8")
    return json_path, markdown_path


def _default_runtime_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return Path(local_app_data) / "ORION" / "runtime"


def _default_output_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return Path(local_app_data) / "ORION" / "development" / "presentation-benchmarks"


async def _run(args: argparse.Namespace) -> tuple[Path, Path, dict[str, Any]]:
    qwen_config = load_yandex_qwen_planner_config(args.runtime_dir)
    realtime_config = YandexRealtimeTextConfig(
        api_key=qwen_config.api_key,
        folder_id=qwen_config.folder_id,
        request_timeout_s=args.request_timeout,
    )
    benchmark = InformationalPresentationBenchmark(
        qwen_config=qwen_config,
        realtime_config=realtime_config,
        capture_rejected_shells=args.diagnostic_rejected_shells,
        diagnostic_capture_limit=args.diagnostic_capture_limit,
    )
    selected_cases = tuple(
        case
        for case in BENCHMARK_CASES
        if not args.case or case.case_id in set(args.case)
    )
    samples = await benchmark.run(
        warm_samples=args.warm_samples,
        qwen_samples=0 if args.skip_qwen else args.qwen_samples,
        cases=selected_cases,
    )
    report = build_report(
        samples,
        warm_samples=args.warm_samples,
        session_ids=benchmark.session_ids,
        diagnostic_rejections=tuple(benchmark.diagnostic_rejections),
        diagnostic_capture_enabled=args.diagnostic_rejected_shells,
        selected_case_ids=tuple(case.case_id for case in selected_cases),
    )
    json_path, markdown_path = write_private_report(report, args.output_dir)
    return json_path, markdown_path, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the private ORION Qwen versus Yandex Realtime text benchmark"
    )
    parser.add_argument("--runtime-dir", type=Path, default=_default_runtime_dir())
    parser.add_argument("--output-dir", type=Path, default=_default_output_dir())
    parser.add_argument("--warm-samples", type=int, default=20)
    parser.add_argument("--qwen-samples", type=int, default=20)
    parser.add_argument("--skip-qwen", action="store_true")
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(case.case_id for case in BENCHMARK_CASES),
        help="Run only the selected synthetic case; repeatable.",
    )
    parser.add_argument("--diagnostic-rejected-shells", action="store_true")
    parser.add_argument("--diagnostic-capture-limit", type=int, default=20)
    parser.add_argument("--request-timeout", type=float, default=8.0)
    args = parser.parse_args()
    if not 1 <= args.warm_samples <= 100 or not 0 <= args.qwen_samples <= 100:
        parser.error("warm samples must be 1..100 and Qwen samples must be 0..100")
    if not 1 <= args.diagnostic_capture_limit <= 100:
        parser.error("diagnostic capture limit must be 1..100")
    if args.diagnostic_rejected_shells and not args.skip_qwen:
        parser.error("rejected-shell diagnostics require --skip-qwen")
    json_path, markdown_path, report = asyncio.run(_run(args))
    provider_calls = len(report["samples"])
    print(f"credential_present=true provider_calls={provider_calls}")
    print(f"benchmark_decision={report['benchmark_decision']}")
    print(f"realtime_candidate_decision={report['realtime_candidate_decision']}")
    print(f"json_report={json_path}")
    print(f"human_report={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
