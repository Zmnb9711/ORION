"""Real-Qwen Mixed FREE + OPERATIONAL Composition Probe."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from orion.airport_surface import RunwayAvailability, RunwayState
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.airport_tower_runtime import AirportTowerController, TowerDepartureState
from orion.atc_core import AtcSessionIdentity
from orion.atc_operations import FreshnessClass
from orion.atc_runtime import AtcCoreFlow
from orion.communication_contracts import CommunicationProfileId
from orion.golden_takeoff_vertical import GoldenTakeoffStatus, GoldenTakeoffVertical
from orion.mixed_conversation import (
    MixedCompositionOutcome,
    MixedConversationDecomposition,
    MixedDecompositionStatus,
    MixedOperationalIntent,
    MixedProviderResult,
    MixedProviderStatus,
    build_mixed_composition,
    request_mixed_decomposition,
)
from orion.pilot_phraseology import PilotPhraseologyResolver
from orion.pilot_phraseology_catalog import build_pilot_phraseology_catalog
from orion.planner import PlannerProvider
from orion.yandex_qwen_planner import (
    QWEN_MODEL_ID,
    YandexPlannerConfigurationError,
    YandexQwenPlannerProvider,
    load_yandex_qwen_planner_config,
)


CALLSIGN = "Viper 2-1"
RUNWAY = "07/25"
SELECTED_PROFILE = CommunicationProfileId.FAP_RUSSIAN_ATC
PROTECTED_TEXT = "Viper 2-1, полоса 07/25, взлёт разрешён."
MAX_CASE_DURATION_MS = 120_000.0


class MixedProbeClassification(StrEnum):
    PASS = "MIXED COMPOSITION PASS"
    FAIL = "MIXED COMPOSITION FAIL"
    BLOCKED_PROVIDER = "BLOCKED_PROVIDER"


@dataclass(frozen=True, slots=True)
class MixedProbeReport:
    classification: MixedProbeClassification
    evidence_path: Path
    evidence_sha256: str
    catalog_sha256: str
    positive_case_count: int
    negative_self_test_count: int
    provider_request_count: int
    provider_attempt_count: int


@dataclass(frozen=True, slots=True)
class _Scenario:
    case_id: str
    utterance: str
    expected_free: bool
    expected_operational: bool
    expected_status: MixedDecompositionStatus
    mixed: bool = False


_SCENARIOS = (
    _Scenario(
        "mixed-ru-1",
        "Добрый день! Разрешите взлёт.",
        True,
        True,
        MixedDecompositionStatus.CLASSIFIED,
        True,
    ),
    _Scenario(
        "mixed-ru-2",
        "Здравствуйте! Можно взлетать?",
        True,
        True,
        MixedDecompositionStatus.CLASSIFIED,
        True,
    ),
    _Scenario(
        "mixed-ru-3",
        "Доброе утро, башня. Готов к взлёту.",
        True,
        True,
        MixedDecompositionStatus.CLASSIFIED,
        True,
    ),
    _Scenario(
        "mixed-ru-4",
        "Башня, приветствую. Запрашиваю разрешение на взлёт.",
        True,
        True,
        MixedDecompositionStatus.CLASSIFIED,
        True,
    ),
    _Scenario(
        "mixed-ru-5",
        "Добрый вечер! Мы готовы, разрешите взлёт.",
        True,
        True,
        MixedDecompositionStatus.CLASSIFIED,
        True,
    ),
    _Scenario(
        "mixed-ru-6",
        "Башня, рад вас слышать. Прошу разрешить взлёт.",
        True,
        True,
        MixedDecompositionStatus.CLASSIFIED,
        True,
    ),
    _Scenario(
        "control-pure-operational",
        "Разрешите взлёт.",
        False,
        True,
        MixedDecompositionStatus.CLASSIFIED,
    ),
    _Scenario(
        "control-pure-conversational",
        "Добрый день! Как дела?",
        True,
        False,
        MixedDecompositionStatus.CLASSIFIED,
    ),
    _Scenario(
        "control-aviation-non-takeoff",
        "Башня, запрашиваю разрешение на посадку.",
        False,
        False,
        MixedDecompositionStatus.UNSUPPORTED,
    ),
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fixture(case_id: str) -> tuple[AtcSessionIdentity, AirportTowerController]:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    tower = AirportTowerController(surface)
    identity = AtcSessionIdentity(
        session_id=uuid5(NAMESPACE_URL, f"orion-mixed-composition:{case_id}"),
        mission_id="mixed-composition-provider-probe",
        aircraft_id=CALLSIGN,
        facility_id="Golden Tower",
    )
    core.open_session(identity)
    tower.assume_runway_control(identity.session_id, reason="Mixed Probe fixture")
    tower.start_departure(session_id=identity.session_id, runway_id=RUNWAY)
    surface.runways.observe(
        RunwayState(
            runway_id=RUNWAY,
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="Mixed Probe deterministic permitted context",
        )
    )
    return identity, tower


def _run_case(
    scenario: _Scenario,
    provider: PlannerProvider,
) -> tuple[dict[str, Any], MixedProviderResult]:
    identity, tower = _fixture(scenario.case_id)
    initial_departure = tower._require_departure(identity.session_id)
    initial_runway = tower.surface.runways.get(RUNWAY)
    interaction_id = uuid5(NAMESPACE_URL, f"orion-mixed-interaction:{scenario.case_id}")
    started = time.perf_counter()
    provider_result = request_mixed_decomposition(
        provider,
        utterance=scenario.utterance,
        interaction_id=interaction_id,
        planner_task_id=f"mixed-{scenario.case_id}",
        # Two existing 45-second transport windows fit under one Core deadline.
        deadline=datetime.now(UTC) + timedelta(seconds=105),
        max_attempts=2,
    )
    outcome: MixedCompositionOutcome | None = None
    if provider_result.decomposition is not None:
        vertical = GoldenTakeoffVertical(
            tower,
            PilotPhraseologyResolver(build_pilot_phraseology_catalog()),
            profile_id=SELECTED_PROFILE,
        )
        outcome = build_mixed_composition(
            decomposition=provider_result.decomposition,
            identity=identity,
            utterance=scenario.utterance,
            interaction_id=interaction_id,
            vertical=vertical,
            profile_id=SELECTED_PROFILE,
        )
    duration_ms = round((time.perf_counter() - started) * 1_000.0, 3)
    final_departure = tower._require_departure(identity.session_id)
    decomposition = provider_result.decomposition
    operational = (
        tuple(decomposition.operational_intents) if decomposition is not None else ()
    )
    has_free = bool(decomposition and decomposition.free_semantics)
    golden = outcome.golden_result if outcome is not None else None
    plan = outcome.plan if outcome is not None else None
    protected = (
        plan.protected_fragments[0]
        if plan is not None and len(plan.protected_fragments) == 1
        else None
    )
    expected_entry = (
        "atc-takeoff-clearance-granted" if scenario.expected_operational else None
    )
    assertions = {
        "bounded_duration": duration_ms <= MAX_CASE_DURATION_MS,
        "provider_completed": provider_result.status is MixedProviderStatus.COMPLETED,
        "detected_ru_independent_of_profile": (
            decomposition is not None
            and decomposition.detected_input_language == "ru-RU"
            and SELECTED_PROFILE is CommunicationProfileId.FAP_RUSSIAN_ATC
        ),
        "expected_decomposition_status": (
            decomposition is not None and decomposition.status is scenario.expected_status
        ),
        "expected_free_presence": has_free is scenario.expected_free,
        "free_is_semantic_not_literal": (
            not scenario.expected_free
            or (
                decomposition is not None
                and bool(decomposition.free_source_text)
                and bool(decomposition.free_response_text)
                and len(decomposition.free_response_text or "") <= 240
                and (decomposition.free_source_text or "").casefold()
                in scenario.utterance.casefold()
            )
        ),
        "expected_operational_intent": (
            operational
            == (
                (MixedOperationalIntent.TAKEOFF_CLEARANCE_REQUEST,)
                if scenario.expected_operational
                else ()
            )
        ),
        "qwen_did_not_decide_clearance": (
            decomposition is not None
            and "decision" not in decomposition.model_dump(mode="json")
        ),
        "atc_is_sole_decision_authority": (
            (
                scenario.expected_operational
                and golden is not None
                and golden.status is GoldenTakeoffStatus.GRANTED
                and golden.decision is not None
                and golden.decision.instruction is not None
                and golden.decision.instruction.semantic_action == "takeoff_clearance"
                and final_departure.state is TowerDepartureState.TAKEOFF_CLEARED
            )
            or (
                not scenario.expected_operational
                and golden is None
                and final_departure.state is TowerDepartureState.HOLD_SHORT
            )
        ),
        "selected_profile_exact": (
            plan is None or plan.communication.profile_id is SELECTED_PROFILE
        ),
        "expected_phrase_entry": (
            (expected_entry is None and golden is None)
            or (
                golden is not None
                and golden.resolution is not None
                and golden.resolution.selected_entry_id == expected_entry
            )
        ),
        "protected_fragment_exact": (
            (not scenario.expected_operational and protected is None)
            or (
                protected is not None
                and protected.text == PROTECTED_TEXT
                and outcome is not None
                and outcome.final_text is not None
                and outcome.final_text.count(PROTECTED_TEXT) == 1
            )
        ),
        "protected_slots_exact": (
            (not scenario.expected_operational and protected is None)
            or (
                protected is not None
                and {
                    item.key: item.value
                    for item in protected.semantic_unit.protected_values
                }
                == {"atc.callsign": CALLSIGN, "atc.runway_id": RUNWAY}
            )
        ),
        "mixed_contains_free_then_protected": (
            not scenario.mixed
            or (
                plan is not None
                and plan.envelope is not None
                and len(plan.protected_fragments) == 1
                and outcome is not None
                and outcome.final_text
                == f"{plan.envelope.text} {plan.protected_fragments[0].text}"
            )
        ),
        "controls_never_gain_takeoff": (
            scenario.expected_operational
            or (golden is None and protected is None)
        ),
    }
    usage = provider_result.usage
    segments: list[dict[str, str]] = []
    if plan is not None and plan.envelope is not None:
        segments.append({"classification": "FREE", "text": plan.envelope.text})
    if protected is not None:
        segments.append({"classification": "PROTECTED", "text": protected.text})
    record = {
        "record_type": "positive_case",
        "case_id": scenario.case_id,
        "original_utterance": scenario.utterance,
        "provider_status": provider_result.status.value,
        "provider_request_ids": list(usage.provider_request_ids) if usage else [],
        "provider_attempts": usage.provider_attempts if usage else None,
        "provider_latency_ms": usage.provider_latency_ms if usage else None,
        "provider_model": usage.model_identifier if usage else QWEN_MODEL_ID,
        "detected_input_language": (
            decomposition.detected_input_language if decomposition else None
        ),
        "safe_normalized_decomposition": (
            decomposition.model_dump(mode="json") if decomposition else None
        ),
        "free_semantic_component": (
            {
                "kinds": [item.value for item in decomposition.free_semantics],
                "source_text": decomposition.free_source_text,
            }
            if decomposition and decomposition.free_semantics
            else None
        ),
        "generated_free_response": (
            decomposition.free_response_text if decomposition else None
        ),
        "operational_semantic_component": [item.value for item in operational],
        "selected_communication_profile": SELECTED_PROFILE.value,
        "atc_initial_context": {
            "callsign": identity.aircraft_id,
            "departure_state": initial_departure.state.value,
            "runway_id": initial_departure.runway_id,
            "runway_availability": initial_runway.availability.value,
            "runway_freshness": initial_runway.freshness.value,
            "tower_authority_established": True,
        },
        "atc_decision": (
            {
                "status": golden.decision.status.value,
                "reason_code": golden.decision.reason_code,
                "initial_state": golden.decision.initial_departure_state.value,
                "final_state": golden.decision.final_departure_state.value,
                "instruction_action": golden.decision.instruction.semantic_action,
                "instruction_parameters": golden.decision.instruction.parameters,
            }
            if golden is not None
            and golden.decision is not None
            and golden.decision.instruction is not None
            and golden.decision.initial_departure_state is not None
            and golden.decision.final_departure_state is not None
            else None
        ),
        "operational_semantic_unit": (
            golden.semantic_unit.model_dump(mode="json")
            if golden is not None and golden.semantic_unit is not None
            else None
        ),
        "selected_phraseology_entry": (
            golden.resolution.selected_entry_id
            if golden is not None and golden.resolution is not None
            else None
        ),
        "protected_slots": (
            [
                item.model_dump(mode="json")
                for item in protected.semantic_unit.protected_values
            ]
            if protected is not None
            else []
        ),
        "protected_operational_fragment": (
            protected.text if protected is not None else None
        ),
        "response_composition_plan": (
            plan.model_dump(mode="json") if plan is not None else None
        ),
        "composition_segments": segments,
        "final_composed_text": outcome.final_text if outcome is not None else None,
        "final_atc_state": final_departure.state.value,
        "validation_assertions": assertions,
        "duration_ms": duration_ms,
        "overall": "PASS" if all(assertions.values()) else "FAIL",
    }
    return record, provider_result


def _canonical_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key
        not in {
            "duration_ms",
            "provider_latency_ms",
            "provider_request_ids",
            "validation_assertions",
        }
    }


def validate_mixed_records(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> tuple[str, ...]:
    issues: list[str] = []
    expected_ids = [row["case_id"] for row in expected]
    actual_ids = [row.get("case_id") for row in actual]
    for case_id in expected_ids:
        count = actual_ids.count(case_id)
        if count == 0:
            issues.append(f"dropped:{case_id}")
        elif count > 1:
            issues.append(f"duplicate:{case_id}")
    for case_id in actual_ids:
        if case_id not in expected_ids:
            issues.append(f"unexpected:{case_id}")
    actual_unique = {
        row["case_id"]: row
        for row in actual
        if actual_ids.count(row.get("case_id")) == 1
        and row.get("case_id") in expected_ids
    }
    for expected_row in expected:
        actual_row = actual_unique.get(expected_row["case_id"])
        if actual_row is not None and _canonical_record(actual_row) != _canonical_record(
            expected_row
        ):
            issues.append(f"changed:{expected_row['case_id']}")
    return tuple(sorted(set(issues)))


def _record(records: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    return next(row for row in records if row["case_id"] == case_id)


def _run_negative_self_tests(
    expected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mutations: tuple[tuple[str, Any], ...] = (
        (
            "missing-operational-intent",
            lambda rows: _record(rows, "mixed-ru-1")[
                "safe_normalized_decomposition"
            ].update(operational_intents=[]),
        ),
        (
            "false-takeoff-on-pure-conversation",
            lambda rows: _record(rows, "control-pure-conversational")[
                "safe_normalized_decomposition"
            ].update(operational_intents=["takeoff_clearance_request"]),
        ),
        (
            "false-takeoff-on-aviation-control",
            lambda rows: _record(rows, "control-aviation-non-takeoff")[
                "safe_normalized_decomposition"
            ].update(operational_intents=["takeoff_clearance_request"]),
        ),
        (
            "malformed-provider-output",
            lambda rows: _record(rows, "mixed-ru-2").update(
                safe_normalized_decomposition={"malformed": True}
            ),
        ),
        (
            "unknown-operational-intent",
            lambda rows: _record(rows, "mixed-ru-3")[
                "safe_normalized_decomposition"
            ].update(operational_intents=["landing_clearance_request"]),
        ),
        (
            "qwen-operational-decision-field",
            lambda rows: _record(rows, "mixed-ru-4")[
                "safe_normalized_decomposition"
            ].update(operational_decision="granted"),
        ),
        (
            "protected-fragment-modified",
            lambda rows: _record(rows, "mixed-ru-5").update(
                protected_operational_fragment="Изменённый фрагмент"
            ),
        ),
        (
            "callsign-modified",
            lambda rows: _record(rows, "mixed-ru-6")["protected_slots"][0].update(
                value="Colt 1-1"
            ),
        ),
        (
            "runway-modified",
            lambda rows: _record(rows, "mixed-ru-1")["protected_slots"][1].update(
                value="25"
            ),
        ),
        (
            "wrong-communication-profile",
            lambda rows: _record(rows, "mixed-ru-2").update(
                selected_communication_profile=CommunicationProfileId.NATO_MILITARY.value
            ),
        ),
        (
            "free-marked-protected",
            lambda rows: _record(rows, "mixed-ru-3")["composition_segments"][0].update(
                classification="PROTECTED"
            ),
        ),
        (
            "protected-marked-free",
            lambda rows: _record(rows, "mixed-ru-4")["composition_segments"][1].update(
                classification="FREE"
            ),
        ),
        (
            "duplicate-protected-fragment",
            lambda rows: _record(rows, "mixed-ru-5")["composition_segments"].append(
                copy.deepcopy(_record(rows, "mixed-ru-5")["composition_segments"][1])
            ),
        ),
        (
            "dropped-protected-fragment",
            lambda rows: _record(rows, "mixed-ru-6")["composition_segments"].pop(),
        ),
    )
    results: list[dict[str, Any]] = []
    for name, mutate in mutations:
        corrupted = copy.deepcopy(expected)
        mutate(corrupted)
        issues = validate_mixed_records(expected, corrupted)
        results.append(
            {
                "record_type": "negative_self_test",
                "case_id": f"self-test:{name}",
                "injected_defect": name,
                "detected": bool(issues),
                "detected_issues": list(issues),
                "overall": "PASS" if issues else "FAIL",
            }
        )
    return results


def _default_runtime_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.cwd()
    return root / "ORION" / "runtime"


def _write_evidence(
    *,
    destination: Path,
    classification: MixedProbeClassification,
    records: list[dict[str, Any]],
    self_tests: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[Path, str]:
    catalog = build_pilot_phraseology_catalog()
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = destination / f"ORION-Mixed-Composition-Evidence-{stamp}.zip"
    manifest = "\n".join(
        (
            "ORION Qwen Mixed FREE + OPERATIONAL Composition Evidence",
            "format_version=1",
            "experimental_non_normative=true",
            "members=manifest.txt,summary.json,cases.jsonl,catalog.json",
            f"classification={classification.value}",
            f"catalog_sha256={catalog.sha256}",
            f"positive_case_count={len(records)}",
            f"negative_self_test_count={len(self_tests)}",
            "real_qwen_required=true",
            "audio_used=false",
            "dcs_used=false",
            "srs_used=false",
            "credentials_included=false",
            "provider_bodies_included=false",
            "",
        )
    )
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        archive.writestr("manifest.txt", manifest)
        archive.writestr("summary.json", _canonical_json(summary) + "\n")
        archive.writestr(
            "cases.jsonl",
            "\n".join(_canonical_json(row) for row in [*records, *self_tests])
            + "\n",
        )
        archive.writestr(
            "catalog.json",
            _canonical_json(
                {**catalog.canonical_payload(), "catalog_sha256": catalog.sha256}
            )
            + "\n",
        )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def run_mixed_composition_probe(
    output_dir: Path | None = None,
    *,
    provider: PlannerProvider | None = None,
    runtime_dir: Path | None = None,
) -> MixedProbeReport:
    runtime = runtime_dir or _default_runtime_dir()
    destination = output_dir or runtime / "mixed-composition-evidence"
    provider_blocked_reason: str | None = None
    if provider is None:
        try:
            provider = YandexQwenPlannerProvider(
                load_yandex_qwen_planner_config(runtime)
            )
        except YandexPlannerConfigurationError:
            provider_blocked_reason = "provider_configuration_unavailable"

    records: list[dict[str, Any]] = []
    provider_results: list[MixedProviderResult] = []
    if provider is not None:
        for scenario in _SCENARIOS:
            record, result = _run_case(scenario, provider)
            records.append(record)
            provider_results.append(result)
            if result.status is MixedProviderStatus.PROVIDER_FAILED:
                break
    self_tests = _run_negative_self_tests(records) if len(records) == len(_SCENARIOS) else []
    validation_issues = validate_mixed_records(records, records)
    provider_failed = any(
        result.status is MixedProviderStatus.PROVIDER_FAILED
        for result in provider_results
    )
    invalid_output = any(
        result.status is MixedProviderStatus.INVALID_OUTPUT
        for result in provider_results
    )
    if provider_blocked_reason is not None or provider_failed:
        classification = MixedProbeClassification.BLOCKED_PROVIDER
    elif (
        len(records) == len(_SCENARIOS)
        and all(record["overall"] == "PASS" for record in records)
        and not invalid_output
        and not validation_issues
        and len(self_tests) == 14
        and all(record["overall"] == "PASS" for record in self_tests)
    ):
        classification = MixedProbeClassification.PASS
    else:
        classification = MixedProbeClassification.FAIL

    usages = [result.usage for result in provider_results if result.usage is not None]
    request_ids = [
        request_id for usage in usages for request_id in usage.provider_request_ids
    ]
    attempt_count = sum(usage.provider_attempts or 0 for usage in usages)
    failure_codes = [
        result.error.code.value
        for result in provider_results
        if result.error is not None
    ]
    catalog = build_pilot_phraseology_catalog()
    summary = {
        "classification": classification.value,
        "scope": "real Qwen mixed text decomposition and local composition only",
        "generated_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "selected_communication_profile": SELECTED_PROFILE.value,
        "input_language_profile_independent": True,
        "provider_id": getattr(provider, "provider_id", None),
        "provider_model": QWEN_MODEL_ID,
        "provider_case_request_count": len(provider_results),
        "provider_response_id_count": len(request_ids),
        "provider_attempt_count": attempt_count,
        "provider_retry_count": max(0, attempt_count - len(usages)),
        "provider_failure_codes": failure_codes,
        "provider_blocked_reason": provider_blocked_reason,
        "positive_case_count": len(records),
        "positive_pass_count": sum(row["overall"] == "PASS" for row in records),
        "mixed_case_count": sum(row["case_id"].startswith("mixed-") for row in records),
        "control_case_count": sum(row["case_id"].startswith("control-") for row in records),
        "negative_self_test_count": len(self_tests),
        "negative_self_test_pass_count": sum(
            row["overall"] == "PASS" for row in self_tests
        ),
        "independent_validation_issues": list(validation_issues),
        "catalog_sha256": catalog.sha256,
        "real_qwen_required": True,
        "audio_used": False,
        "dcs_used": False,
        "srs_used": False,
        "credentials_included": False,
        "provider_bodies_included": False,
    }
    evidence_path, evidence_sha256 = _write_evidence(
        destination=destination,
        classification=classification,
        records=records,
        self_tests=self_tests,
        summary=summary,
    )
    return MixedProbeReport(
        classification=classification,
        evidence_path=evidence_path,
        evidence_sha256=evidence_sha256,
        catalog_sha256=catalog.sha256,
        positive_case_count=len(records),
        negative_self_test_count=len(self_tests),
        provider_request_count=len(provider_results),
        provider_attempt_count=attempt_count,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    args = parser.parse_args()
    report = run_mixed_composition_probe(
        args.output_dir,
        runtime_dir=args.runtime_dir,
    )
    print(
        _canonical_json(
            {
                "classification": report.classification.value,
                "evidence_path": str(report.evidence_path),
                "evidence_sha256": report.evidence_sha256,
                "catalog_sha256": report.catalog_sha256,
                "positive_case_count": report.positive_case_count,
                "negative_self_test_count": report.negative_self_test_count,
                "provider_request_count": report.provider_request_count,
                "provider_attempt_count": report.provider_attempt_count,
            }
        )
    )
    return 0 if report.classification is MixedProbeClassification.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
