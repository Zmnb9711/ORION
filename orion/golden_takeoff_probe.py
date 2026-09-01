"""Offline deterministic evidence probe for Golden Conversational Vertical #1."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
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
from orion.golden_takeoff_vertical import (
    GoldenTakeoffResult,
    GoldenTakeoffStatus,
    GoldenTakeoffVertical,
    TakeoffDecisionStatus,
    TakeoffIntentStatus,
)
from orion.pilot_phraseology import PilotPhraseologyResolver
from orion.pilot_phraseology_catalog import build_pilot_phraseology_catalog


MAX_CASE_DURATION_MS = 5_000.0
CALLSIGN = "Viper 2-1"
RUNWAY = "07/25"


class GoldenProbeClassification(StrEnum):
    PASS = "GOLDEN VERTICAL PASS"
    FAIL = "GOLDEN VERTICAL FAIL"


@dataclass(frozen=True, slots=True)
class GoldenProbeReport:
    classification: GoldenProbeClassification
    evidence_path: Path
    evidence_sha256: str
    catalog_sha256: str
    scenario_count: int
    negative_self_test_count: int


@dataclass(frozen=True, slots=True)
class _Scenario:
    case_id: str
    utterance: str
    expected_status: GoldenTakeoffStatus
    runway_availability: RunwayAvailability | None
    runway_freshness: FreshnessClass = FreshnessClass.FRESH


_SCENARIOS = (
    *(
        _Scenario(
            f"permitted-ru-{index}",
            utterance,
            GoldenTakeoffStatus.GRANTED,
            RunwayAvailability.CLEAR,
        )
        for index, utterance in enumerate(
            (
                "Разрешите взлёт!",
                "Разрешите взлёт.",
                "Можно взлетать?",
                "Башня, готов к взлёту.",
                "Готов к взлёту, разрешите взлёт.",
                "Запрашиваю разрешение на взлёт.",
            ),
            start=1,
        )
    ),
    *(
        _Scenario(
            f"permitted-en-{index}",
            utterance,
            GoldenTakeoffStatus.GRANTED,
            RunwayAvailability.CLEAR,
        )
        for index, utterance in enumerate(
            (
                "Tower, request takeoff clearance.",
                "Ready for takeoff.",
                "Request takeoff.",
                "Tower, Viper 2-1 ready for departure.",
            ),
            start=1,
        )
    ),
    _Scenario(
        "blocked-ru",
        "Разрешите взлёт.",
        GoldenTakeoffStatus.HOLD,
        RunwayAvailability.OCCUPIED,
    ),
    _Scenario(
        "blocked-en",
        "Tower, request takeoff clearance.",
        GoldenTakeoffStatus.HOLD,
        RunwayAvailability.OCCUPIED,
    ),
    _Scenario(
        "unavailable-ru",
        "Запрашиваю разрешение на взлёт.",
        GoldenTakeoffStatus.UNAVAILABLE,
        None,
        FreshnessClass.UNKNOWN,
    ),
    _Scenario(
        "unavailable-en",
        "Request takeoff.",
        GoldenTakeoffStatus.UNAVAILABLE,
        None,
        FreshnessClass.UNKNOWN,
    ),
    _Scenario(
        "unsupported-ru",
        "Какая погода?",
        GoldenTakeoffStatus.UNSUPPORTED,
        RunwayAvailability.CLEAR,
    ),
    _Scenario(
        "unsupported-en",
        "Report weather.",
        GoldenTakeoffStatus.UNSUPPORTED,
        RunwayAvailability.CLEAR,
    ),
    _Scenario(
        "ambiguous-ru",
        "Башня, готов.",
        GoldenTakeoffStatus.CLARIFICATION_REQUIRED,
        RunwayAvailability.CLEAR,
    ),
    _Scenario(
        "ambiguous-en",
        "Tower, ready.",
        GoldenTakeoffStatus.CLARIFICATION_REQUIRED,
        RunwayAvailability.CLEAR,
    ),
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fixture(scenario: _Scenario) -> tuple[AtcSessionIdentity, AirportTowerController]:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    tower = AirportTowerController(surface)
    identity = AtcSessionIdentity(
        session_id=uuid5(NAMESPACE_URL, f"orion-golden-takeoff:{scenario.case_id}"),
        mission_id="golden-takeoff-offline-fixture",
        aircraft_id=CALLSIGN,
        facility_id="Golden Tower",
    )
    core.open_session(identity)
    tower.assume_runway_control(identity.session_id, reason="offline Golden fixture")
    tower.start_departure(session_id=identity.session_id, runway_id=RUNWAY)
    if scenario.runway_availability is not None:
        surface.runways.observe(
            RunwayState(
                runway_id=RUNWAY,
                availability=scenario.runway_availability,
                freshness=scenario.runway_freshness,
                reason="offline Golden fixture",
            )
        )
    return identity, tower


def _decision_summary(result: GoldenTakeoffResult) -> dict[str, Any] | None:
    decision = result.decision
    if decision is None:
        return None
    instruction = decision.instruction
    return {
        "status": decision.status.value,
        "reason_code": decision.reason_code,
        "session_id": decision.session_id,
        "callsign": decision.callsign,
        "runway_id": decision.runway_id,
        "initial_departure_state": (
            decision.initial_departure_state.value
            if decision.initial_departure_state is not None
            else None
        ),
        "final_departure_state": (
            decision.final_departure_state.value
            if decision.final_departure_state is not None
            else None
        ),
        "runway_availability": (
            decision.runway_availability.value
            if decision.runway_availability is not None
            else None
        ),
        "runway_freshness": (
            decision.runway_freshness.value
            if decision.runway_freshness is not None
            else None
        ),
        "instruction": (
            {
                "issuing_agency": instruction.issuing_agency.value,
                "authority_scope": instruction.authority_scope.value,
                "semantic_action": instruction.semantic_action,
                "parameters": instruction.parameters,
            }
            if instruction is not None
            else None
        ),
    }


def _run_scenario(scenario: _Scenario) -> dict[str, Any]:
    identity, tower = _fixture(scenario)
    catalog = build_pilot_phraseology_catalog()
    vertical = GoldenTakeoffVertical(tower, PilotPhraseologyResolver(catalog))
    initial_departure = tower._require_departure(identity.session_id)
    initial_runway = tower.surface.runways.get(RUNWAY)
    started = time.perf_counter()
    result = vertical.handle(identity=identity, utterance=scenario.utterance)
    duration_ms = round((time.perf_counter() - started) * 1_000.0, 3)
    departure = tower._require_departure(identity.session_id)
    recognized = result.intent.status is TakeoffIntentStatus.RECOGNIZED
    expected_decision = {
        GoldenTakeoffStatus.GRANTED: TakeoffDecisionStatus.GRANTED,
        GoldenTakeoffStatus.HOLD: TakeoffDecisionStatus.HOLD,
        GoldenTakeoffStatus.UNAVAILABLE: TakeoffDecisionStatus.UNAVAILABLE,
    }.get(scenario.expected_status)
    unit = result.semantic_unit
    fragment = result.fragment
    protected = (
        [item.model_dump(mode="json") for item in unit.protected_values]
        if unit is not None
        else []
    )
    expected_entry = {
        GoldenTakeoffStatus.GRANTED: "atc-takeoff-clearance-granted",
        GoldenTakeoffStatus.HOLD: "atc-takeoff-hold",
        GoldenTakeoffStatus.UNAVAILABLE: "atc-takeoff-context-unavailable",
        GoldenTakeoffStatus.CLARIFICATION_REQUIRED: "general-say-again-fap",
        GoldenTakeoffStatus.UNSUPPORTED: None,
    }[scenario.expected_status]
    assertions = {
        "bounded_duration": duration_ms <= MAX_CASE_DURATION_MS,
        "expected_status": result.status is scenario.expected_status,
        "intent_separate_from_decision": (
            (recognized and result.decision is not None)
            or (
                not recognized
                and result.decision is None
            )
        ),
        "expected_typed_decision": (
            (expected_decision is None and result.decision is None)
            or (
                result.decision is not None
                and result.decision.status is expected_decision
            )
        ),
        "exact_phrase_entry": (
            (expected_entry is None and result.resolution is None)
            or (
                result.resolution is not None
                and result.resolution.selected_entry_id == expected_entry
            )
        ),
        "exact_callsign_and_runway_preserved": (
            scenario.expected_status
            in {
                GoldenTakeoffStatus.CLARIFICATION_REQUIRED,
                GoldenTakeoffStatus.UNSUPPORTED,
            }
            or (
                {item["key"]: item["value"] for item in protected}
                == {"atc.callsign": CALLSIGN, "atc.runway_id": RUNWAY}
            )
        ),
        "atc_state_matches_decision": (
            departure.state is TowerDepartureState.TAKEOFF_CLEARED
            if scenario.expected_status is GoldenTakeoffStatus.GRANTED
            else departure.state is TowerDepartureState.HOLD_SHORT
        ),
        "complete_or_intentionally_stopped_chain": (
            (fragment is None and scenario.expected_status is GoldenTakeoffStatus.UNSUPPORTED)
            or (
                fragment is not None
                and unit is not None
                and fragment.semantic_unit == unit
            )
        ),
    }
    return {
        "record_type": "golden_case",
        "case_id": scenario.case_id,
        "language": result.intent.language,
        "utterance": scenario.utterance,
        "expected_status": scenario.expected_status.value,
        "actual_status": result.status.value,
        "intent": result.intent.model_dump(mode="json"),
        "atc_initial_context": {
            "session_id": str(identity.session_id),
            "callsign": identity.aircraft_id,
            "facility_id": identity.facility_id,
            "departure_state": initial_departure.state.value,
            "runway_id": initial_departure.runway_id,
            "runway_availability": initial_runway.availability.value,
            "runway_freshness": initial_runway.freshness.value,
            "tower_authority_established": True,
        },
        "atc_decision": _decision_summary(result),
        "semantic_unit": unit.model_dump(mode="json") if unit is not None else None,
        "selected_entry_id": (
            result.resolution.selected_entry_id
            if result.resolution is not None
            else None
        ),
        "protected_values": protected,
        "rendered_text": fragment.text if fragment is not None else None,
        "final_atc_state": departure.state.value,
        "validation_assertions": assertions,
        "overall": "PASS" if all(assertions.values()) else "FAIL",
        "duration_ms": duration_ms,
    }


def _canonical_case(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"duration_ms", "validation_assertions"}
    }


def validate_golden_records(
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
        case_id = expected_row["case_id"]
        actual_row = actual_unique.get(case_id)
        if actual_row is None:
            continue
        if _canonical_case(actual_row) != _canonical_case(expected_row):
            issues.append(f"changed:{case_id}")
    return tuple(sorted(set(issues)))


def _record(records: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    return next(row for row in records if row["case_id"] == case_id)


def _run_negative_self_tests(
    expected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mutations: tuple[tuple[str, Any], ...] = (
        (
            "granted-rendered-as-hold",
            lambda rows: _record(rows, "permitted-en-1").update(
                rendered_text=f"{CALLSIGN}, hold position, runway {RUNWAY}."
            ),
        ),
        (
            "denied-rendered-as-clearance",
            lambda rows: _record(rows, "blocked-en").update(
                rendered_text=f"{CALLSIGN}, runway {RUNWAY}, cleared for takeoff."
            ),
        ),
        (
            "wrong-callsign",
            lambda rows: _record(rows, "permitted-en-2")["protected_values"][0].update(
                value="Colt 1-1"
            ),
        ),
        (
            "wrong-runway",
            lambda rows: _record(rows, "permitted-ru-2")["protected_values"][1].update(
                value="25"
            ),
        ),
        (
            "dropped-protected-slot",
            lambda rows: _record(rows, "permitted-en-3")["protected_values"].pop(),
        ),
        (
            "fabricated-protected-slot",
            lambda rows: _record(rows, "unavailable-en")["protected_values"].append(
                {"key": "atc.wind", "kind": "generic", "value": "calm", "unit": None}
            ),
        ),
        (
            "wrong-phrase-entry",
            lambda rows: _record(rows, "permitted-ru-3").update(
                selected_entry_id="atc-takeoff-hold"
            ),
        ),
        (
            "unsupported-misclassified",
            lambda rows: _record(rows, "unsupported-en")["intent"].update(
                status="recognized", kind="takeoff_clearance_request"
            ),
        ),
        (
            "ambiguous-granted",
            lambda rows: _record(rows, "ambiguous-ru").update(actual_status="granted"),
        ),
        ("duplicate-result", lambda rows: rows.append(copy.deepcopy(rows[0]))),
        ("dropped-result", lambda rows: rows.pop(0)),
    )
    results: list[dict[str, Any]] = []
    for name, mutate in mutations:
        corrupted = copy.deepcopy(expected)
        mutate(corrupted)
        issues = validate_golden_records(expected, corrupted)
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


def _canonical_decision(row: dict[str, Any]) -> dict[str, Any] | None:
    decision = row["atc_decision"]
    if decision is None:
        return None
    return {
        key: value
        for key, value in decision.items()
        if key != "session_id"
    }


def _semantic_gates(records: list[dict[str, Any]]) -> dict[str, bool]:
    permitted = [row for row in records if row["case_id"].startswith("permitted-")]
    recognized_intents = {
        (row["intent"]["status"], row["intent"]["kind"])
        for row in permitted
    }
    permitted_decisions = {
        _canonical_json(_canonical_decision(row)) for row in permitted
    }
    category_pairs = (
        ("permitted-ru-1", "permitted-en-1"),
        ("blocked-ru", "blocked-en"),
        ("unavailable-ru", "unavailable-en"),
        ("unsupported-ru", "unsupported-en"),
        ("ambiguous-ru", "ambiguous-en"),
    )
    by_id = {row["case_id"]: row for row in records}
    bilingual_equivalence = all(
        (
            by_id[ru]["actual_status"] == by_id[en]["actual_status"]
            and by_id[ru]["intent"]["status"] == by_id[en]["intent"]["status"]
            and by_id[ru]["intent"]["kind"] == by_id[en]["intent"]["kind"]
            and _canonical_decision(by_id[ru]) == _canonical_decision(by_id[en])
            and by_id[ru]["protected_values"] == by_id[en]["protected_values"]
        )
        for ru, en in category_pairs
    )
    unavailable = [
        by_id["unavailable-ru"],
        by_id["unavailable-en"],
    ]
    unavailable_values_not_fabricated = all(
        {item["key"]: item["value"] for item in row["protected_values"]}
        == {
            "atc.callsign": row["atc_initial_context"]["callsign"],
            "atc.runway_id": row["atc_initial_context"]["runway_id"],
        }
        for row in unavailable
    )
    return {
        "approved_variants_same_canonical_intent": recognized_intents
        == {("recognized", "takeoff_clearance_request")},
        "different_wording_same_permitted_decision": len(permitted_decisions) == 1,
        "ru_en_canonical_decision_equivalent": bilingual_equivalence,
        "unavailable_values_not_fabricated": unavailable_values_not_fabricated,
    }


def _default_output_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.cwd()
    return root / "ORION" / "runtime" / "golden-takeoff-evidence"


def run_golden_takeoff_probe(output_dir: Path | None = None) -> GoldenProbeReport:
    first = [_run_scenario(scenario) for scenario in _SCENARIOS]
    second = [_run_scenario(scenario) for scenario in _SCENARIOS]
    deterministic = [_canonical_case(row) for row in first] == [
        _canonical_case(row) for row in second
    ]
    semantic_gates = _semantic_gates(first)
    self_tests = _run_negative_self_tests(first)
    validation_issues = validate_golden_records(first, first)
    classification = (
        GoldenProbeClassification.PASS
        if (
            len(first) == len(_SCENARIOS)
            and all(row["overall"] == "PASS" for row in first)
            and deterministic
            and all(semantic_gates.values())
            and not validation_issues
            and len(self_tests) == 11
            and all(row["overall"] == "PASS" for row in self_tests)
        )
        else GoldenProbeClassification.FAIL
    )
    catalog = build_pilot_phraseology_catalog()
    summary = {
        "classification": classification.value,
        "scope": "offline Golden Conversational Vertical #1 only",
        "experimental_non_normative": True,
        "generated_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "catalog_version": catalog.version,
        "catalog_sha256": catalog.sha256,
        "scenario_count": len(first),
        "scenario_pass_count": sum(row["overall"] == "PASS" for row in first),
        "negative_self_test_count": len(self_tests),
        "negative_self_test_pass_count": sum(
            row["overall"] == "PASS" for row in self_tests
        ),
        "fresh_vertical_repeat_deterministic": deterministic,
        **semantic_gates,
        "independent_validation_issues": list(validation_issues),
        "network_used": False,
        "provider_used": False,
        "dcs_used": False,
        "srs_used": False,
        "audio_devices_used": False,
        "credentials_included": False,
    }
    manifest = "\n".join(
        (
            "ORION Golden Conversational Vertical #1 Evidence",
            "format_version=1",
            "experimental_non_normative=true",
            "members=manifest.txt,summary.json,cases.jsonl,catalog.json",
            f"classification={classification.value}",
            f"catalog_sha256={catalog.sha256}",
            f"scenario_count={len(first)}",
            f"negative_self_test_count={len(self_tests)}",
            "network_used=false",
            "provider_used=false",
            "dcs_used=false",
            "srs_used=false",
            "audio_devices_used=false",
            "credentials_included=false",
            "",
        )
    )
    destination = output_dir or _default_output_dir()
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    evidence_path = destination / f"ORION-Golden-Takeoff-Evidence-{stamp}.zip"
    with zipfile.ZipFile(
        evidence_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        archive.writestr("manifest.txt", manifest)
        archive.writestr("summary.json", _canonical_json(summary) + "\n")
        archive.writestr(
            "cases.jsonl",
            "\n".join(_canonical_json(row) for row in [*first, *self_tests]) + "\n",
        )
        archive.writestr(
            "catalog.json",
            _canonical_json(
                {**catalog.canonical_payload(), "catalog_sha256": catalog.sha256}
            )
            + "\n",
        )
    return GoldenProbeReport(
        classification=classification,
        evidence_path=evidence_path,
        evidence_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        catalog_sha256=catalog.sha256,
        scenario_count=len(first),
        negative_self_test_count=len(self_tests),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report = run_golden_takeoff_probe(args.output_dir)
    print(
        _canonical_json(
            {
                "classification": report.classification.value,
                "evidence_path": str(report.evidence_path),
                "evidence_sha256": report.evidence_sha256,
                "catalog_sha256": report.catalog_sha256,
                "scenario_count": report.scenario_count,
                "negative_self_test_count": report.negative_self_test_count,
            }
        )
    )
    return 0 if report.classification is GoldenProbeClassification.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
