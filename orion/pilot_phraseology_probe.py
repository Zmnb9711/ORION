"""Offline deterministic Test Probe for the experimental Pilot phraseology KB."""

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
from uuid import uuid4

from orion.communication_contracts import (
    CommunicationContext,
    CommunicationPriority,
    ContextReference,
    OperationalSemanticUnit,
    ProtectedProvenance,
    ProtectedValue,
    ProtectedValueKind,
)
from orion.pilot_phraseology import (
    SUPPORTED_LANGUAGES,
    PilotPhraseologyCatalog,
    PilotPhraseologyEntry,
    PilotPhraseologyResolver,
    PilotResolutionStatus,
)
from orion.pilot_phraseology_catalog import build_pilot_phraseology_catalog
from orion.world_model_contracts import WorldFactAuthority


MAX_CASE_DURATION_MS = 5_000.0


class PilotProbeClassification(StrEnum):
    PASS = "PILOT PASS"
    FAIL = "PILOT FAIL"


@dataclass(frozen=True, slots=True)
class PilotProbeReport:
    classification: PilotProbeClassification
    evidence_path: Path
    evidence_sha256: str
    catalog_sha256: str
    semantic_entry_count: int
    positive_case_count: int
    negative_self_test_count: int


_SAMPLE_VALUES: dict[str, str | int] = {
    "atc.callsign": "Viper 2-1",
    "atc.runway_id": "07/25",
    "radio.callsign": "Viper 2-1",
    "radio.frequency_mhz": "264.500",
    "radio.modulation": "AM",
    "ownship.heading_deg": 137,
    "ownship.altitude_ft": 12450,
    "ownship.speed_kt": 286,
    "navigation.range_nm": 63,
    "navigation.bearing_deg": 245,
    "navigation.vertical_offset_ft": -850,
    "navigation.tacan_channel": "44X",
    "jtac.laser_code": "1577",
    "ownship.position.latitude": "42.100000",
    "ownship.position.longitude": "41.200000",
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fixture_unit(entry: PilotPhraseologyEntry) -> OperationalSemanticUnit:
    protected_values = tuple(
        ProtectedValue(
            key=slot.semantic_key,
            kind=slot.expected_kind,
            value=_SAMPLE_VALUES[slot.semantic_key],
            unit=slot.expected_unit,
        )
        for slot in entry.slots
    )
    return OperationalSemanticUnit(
        unit_type=entry.selector.unit_type,
        semantic_meaning=entry.selector.semantic_meaning,
        domain=entry.selector.domain,
        priority=(
            CommunicationPriority.URGENT
            if entry.selector.status == "warning"
            else CommunicationPriority.IMPORTANT
        ),
        status=entry.selector.status,
        polarity=entry.selector.polarity,
        protected_values=protected_values,
        provenance=(
            ProtectedProvenance(
                source=ContextReference(
                    context_type="pilot_probe",
                    reference_id=f"fixture-{entry.entry_id}",
                ),
                authority=WorldFactAuthority.AUTHORITATIVE,
                generation="pilot-fixture-v1",
                domain_origin=entry.selector.domain,
            ),
        ),
    )


def _protected_values(unit: OperationalSemanticUnit) -> list[dict[str, object]]:
    return [value.model_dump(mode="json") for value in unit.protected_values]


def _run_positive_corpus(
    catalog: PilotPhraseologyCatalog,
) -> list[dict[str, Any]]:
    resolver = PilotPhraseologyResolver(catalog)
    records: list[dict[str, Any]] = []
    for entry in sorted(catalog.entries, key=lambda item: item.entry_id):
        unit = _fixture_unit(entry)
        for language in SUPPORTED_LANGUAGES:
            context = CommunicationContext(
                profile_id=entry.selector.profile_id,
                domain=entry.selector.domain,
                operational_language=language,
                phraseology_snapshot_id=catalog.sha256,
                phraseology_version=catalog.version,
            )
            started = time.perf_counter()
            result = resolver.resolve(context, unit)
            duration_ms = round((time.perf_counter() - started) * 1_000.0, 3)
            fragment = result.fragment
            assertions = {
                "bounded_duration": duration_ms <= MAX_CASE_DURATION_MS,
                "correct_entry": result.selected_entry_id == entry.entry_id,
                "exactly_one_rendered_result": (
                    result.status is PilotResolutionStatus.RENDERED
                    and fragment is not None
                ),
                "protected_unit_unchanged": (
                    fragment is not None and fragment.semantic_unit == unit
                ),
                "slot_count_preserved": len(result.resolved_slots) == len(entry.slots),
            }
            overall = "PASS" if all(assertions.values()) else "FAIL"
            values = _protected_values(unit)
            records.append(
                {
                    "record_type": "positive_case",
                    "case_id": f"{entry.entry_id}:{language}",
                    "correlation_id": uuid4().hex,
                    "catalog_sha256": catalog.sha256,
                    "communication_profile": entry.selector.profile_id.value,
                    "domain": entry.selector.domain.value,
                    "language": language,
                    "semantic_meaning": unit.semantic_meaning,
                    "semantic_status": unit.status,
                    "semantic_polarity": unit.polarity,
                    "resolution_status": result.status.value,
                    "input_protected_values": values,
                    "input_units": {value["key"]: value["unit"] for value in values},
                    "provenance": [
                        item.model_dump(mode="json") for item in unit.provenance
                    ],
                    "expected_entry_id": entry.entry_id,
                    "selected_entry_id": result.selected_entry_id,
                    "resolved_slots": [
                        item.model_dump(mode="json") for item in result.resolved_slots
                    ],
                    "rendered_text": fragment.text if fragment is not None else None,
                    "expected_protected_semantic_values": values,
                    "validation_assertions": assertions,
                    "overall": overall,
                    "typed_failure": (
                        None
                        if result.failure_reason is None
                        else {
                            "status": result.status.value,
                            "reason": result.failure_reason,
                        }
                    ),
                    "duration_ms": duration_ms,
                }
            )
    return records


def _canonical_case(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (
            "case_id",
            "catalog_sha256",
            "communication_profile",
            "domain",
            "language",
            "semantic_meaning",
            "semantic_status",
            "semantic_polarity",
            "resolution_status",
            "input_protected_values",
            "input_units",
            "provenance",
            "expected_entry_id",
            "selected_entry_id",
            "resolved_slots",
            "rendered_text",
            "expected_protected_semantic_values",
            "overall",
            "typed_failure",
        )
    }


def validate_probe_records(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> tuple[str, ...]:
    """Independently detect dropped, duplicated, or semantically changed cases."""

    issues: list[str] = []
    expected_ids = [record["case_id"] for record in expected]
    actual_ids = [record.get("case_id") for record in actual]
    for case_id in expected_ids:
        count = actual_ids.count(case_id)
        if count == 0:
            issues.append(f"dropped:{case_id}")
        elif count > 1:
            issues.append(f"duplicate:{case_id}")
    for case_id in actual_ids:
        if case_id not in expected_ids:
            issues.append(f"unexpected:{case_id}")

    actual_by_id = {
        record["case_id"]: record
        for record in actual
        if actual_ids.count(record.get("case_id")) == 1
        and record.get("case_id") in expected_ids
    }
    for expected_record in expected:
        case_id = expected_record["case_id"]
        actual_record = actual_by_id.get(case_id)
        if actual_record is None:
            continue
        for field in (
            "catalog_sha256",
            "communication_profile",
            "domain",
            "language",
            "semantic_meaning",
            "semantic_status",
            "semantic_polarity",
            "resolution_status",
            "input_protected_values",
            "input_units",
            "provenance",
            "expected_entry_id",
            "selected_entry_id",
            "resolved_slots",
            "rendered_text",
            "expected_protected_semantic_values",
            "overall",
            "typed_failure",
        ):
            if actual_record.get(field) != expected_record.get(field):
                issues.append(f"changed:{case_id}:{field}")
    return tuple(sorted(set(issues)))


def _record_for(records: list[dict[str, Any]], entry_id: str) -> dict[str, Any]:
    return next(
        record for record in records if record["case_id"] == f"{entry_id}:en-US"
    )


def _mutate_protected(
    records: list[dict[str, Any]],
    entry_id: str,
    key: str,
    field: str,
    value: object,
) -> None:
    record = _record_for(records, entry_id)
    protected = next(
        item for item in record["input_protected_values"] if item["key"] == key
    )
    protected[field] = value
    if field == "unit":
        record["input_units"][key] = value


def _run_negative_self_tests(
    expected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mutations: list[tuple[str, Any]] = []

    def add(name: str, mutate: Any) -> None:
        mutations.append((name, mutate))

    add(
        "frequency-264500-to-264050",
        lambda rows: _mutate_protected(
            rows,
            "radio-frequency-modulation",
            "radio.frequency_mhz",
            "value",
            "264.050",
        ),
    )
    add(
        "modulation-am-to-fm",
        lambda rows: _mutate_protected(
            rows, "radio-frequency-modulation", "radio.modulation", "value", "FM"
        ),
    )
    add(
        "tacan-44x-to-44y",
        lambda rows: _mutate_protected(
            rows,
            "navigation-tacan-available",
            "navigation.tacan_channel",
            "value",
            "44Y",
        ),
    )
    add(
        "laser-1577-to-157",
        lambda rows: _mutate_protected(
            rows, "jtac-laser-code", "jtac.laser_code", "value", "157"
        ),
    )
    add(
        "sign-negative-to-positive",
        lambda rows: _mutate_protected(
            rows,
            "navigation-signed-correction",
            "navigation.vertical_offset_ft",
            "value",
            850,
        ),
    )
    add(
        "frequency-unit-mhz-to-khz",
        lambda rows: _mutate_protected(
            rows, "radio-frequency", "radio.frequency_mhz", "unit", "kHz"
        ),
    )
    add(
        "offset-unit-ft-to-m",
        lambda rows: _mutate_protected(
            rows,
            "navigation-signed-correction",
            "navigation.vertical_offset_ft",
            "unit",
            "m",
        ),
    )

    def fabricate_tacan(rows: list[dict[str, Any]]) -> None:
        record = _record_for(rows, "navigation-tacan-unavailable")
        record["input_protected_values"].append(
            {
                "key": "navigation.tacan_channel",
                "kind": ProtectedValueKind.TACAN.value,
                "value": "44X",
                "unit": None,
            }
        )
        record["input_units"]["navigation.tacan_channel"] = None

    add("unavailable-tacan-fabricated", fabricate_tacan)

    def remove_slot(rows: list[dict[str, Any]]) -> None:
        _record_for(rows, "radio-frequency")["resolved_slots"] = []

    add("missing-required-slot", remove_slot)

    def wrong_entry(rows: list[dict[str, Any]]) -> None:
        _record_for(rows, "navigation-heading")["selected_entry_id"] = (
            "navigation-speed"
        )

    add("wrong-selected-entry-id", wrong_entry)
    add("duplicate-result", lambda rows: rows.append(copy.deepcopy(rows[0])))
    add("dropped-result", lambda rows: rows.pop(0))

    results: list[dict[str, Any]] = []
    for name, mutate in mutations:
        corrupted = copy.deepcopy(expected)
        mutate(corrupted)
        issues = validate_probe_records(expected, corrupted)
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


def _languages_semantically_equivalent(records: list[dict[str, Any]]) -> bool:
    by_entry: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        by_entry.setdefault(record["expected_entry_id"], {})[record["language"]] = (
            record
        )
    compared_fields = (
        "catalog_sha256",
        "communication_profile",
        "domain",
        "semantic_meaning",
        "semantic_status",
        "semantic_polarity",
        "input_protected_values",
        "input_units",
        "provenance",
        "expected_entry_id",
        "selected_entry_id",
        "resolved_slots",
    )
    for pair in by_entry.values():
        if set(pair) != set(SUPPORTED_LANGUAGES):
            return False
        en_us = pair["en-US"]
        ru_ru = pair["ru-RU"]
        if any(en_us[field] != ru_ru[field] for field in compared_fields):
            return False
    return True


def _default_output_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.cwd()
    return root / "ORION" / "runtime" / "pilot-phraseology-evidence"


def run_pilot_phraseology_probe(output_dir: Path | None = None) -> PilotProbeReport:
    """Run the network/audio-free Pilot Probe and write one bounded ZIP bundle."""

    catalog_first = build_pilot_phraseology_catalog()
    catalog_second = build_pilot_phraseology_catalog()
    first = _run_positive_corpus(catalog_first)
    second = _run_positive_corpus(catalog_second)
    expected_positive_count = len(catalog_first.entries) * len(SUPPORTED_LANGUAGES)
    deterministic = catalog_first.sha256 == catalog_second.sha256 and [
        _canonical_case(record) for record in first
    ] == [_canonical_case(record) for record in second]
    self_tests = _run_negative_self_tests(first)
    independent_validation = validate_probe_records(first, first)
    positive_pass = (
        len(first) == expected_positive_count
        and all(record["overall"] == "PASS" for record in first)
        and not independent_validation
    )
    self_tests_pass = all(record["overall"] == "PASS" for record in self_tests)
    language_equivalence = _languages_semantically_equivalent(first)
    bounded_catalog = 20 <= len(catalog_first.entries) <= 30
    classification = (
        PilotProbeClassification.PASS
        if all(
            (
                bounded_catalog,
                positive_pass,
                deterministic,
                language_equivalence,
                self_tests_pass,
            )
        )
        else PilotProbeClassification.FAIL
    )

    catalog_payload = catalog_first.canonical_payload()
    catalog_evidence = {
        **catalog_payload,
        "catalog_sha256": catalog_first.sha256,
    }
    generated_at = datetime.now(UTC).isoformat(timespec="milliseconds")
    summary = {
        "classification": classification.value,
        "scope": "offline Pilot phraseology semantics only",
        "experimental_non_normative": True,
        "generated_at": generated_at,
        "catalog_version": catalog_first.version,
        "catalog_sha256": catalog_first.sha256,
        "semantic_entry_count": len(catalog_first.entries),
        "language_count": len(SUPPORTED_LANGUAGES),
        "languages": list(SUPPORTED_LANGUAGES),
        "expected_positive_result_count": expected_positive_count,
        "actual_positive_result_count": len(first),
        "positive_pass_count": sum(record["overall"] == "PASS" for record in first),
        "negative_self_test_count": len(self_tests),
        "negative_self_test_pass_count": sum(
            record["overall"] == "PASS" for record in self_tests
        ),
        "catalog_hash_stable": catalog_first.sha256 == catalog_second.sha256,
        "fresh_resolver_repeat_deterministic": deterministic,
        "ru_en_semantic_equivalence": language_equivalence,
        "independent_validation_issues": list(independent_validation),
        "network_used": False,
        "provider_used": False,
        "dcs_used": False,
        "srs_used": False,
        "audio_devices_used": False,
        "credentials_included": False,
    }
    cases = (
        "\n".join(_canonical_json(record) for record in [*first, *self_tests]) + "\n"
    )
    catalog_json = _canonical_json(catalog_evidence) + "\n"
    summary_json = _canonical_json(summary) + "\n"
    manifest = "\n".join(
        (
            "ORION Pilot Phraseology Test Evidence",
            "format_version=1",
            "experimental_non_normative=true",
            "members=manifest.txt,summary.json,cases.jsonl,catalog.json",
            f"classification={classification.value}",
            f"catalog_version={catalog_first.version}",
            f"catalog_sha256={catalog_first.sha256}",
            f"semantic_entry_count={len(catalog_first.entries)}",
            f"language_count={len(SUPPORTED_LANGUAGES)}",
            f"expected_positive_result_count={expected_positive_count}",
            f"actual_positive_result_count={len(first)}",
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
    evidence_path = destination / (
        f"ORION-Pilot-Phraseology-Evidence-{stamp}-{uuid4().hex[:8]}.zip"
    )
    with zipfile.ZipFile(
        evidence_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        archive.writestr("manifest.txt", manifest)
        archive.writestr("summary.json", summary_json)
        archive.writestr("cases.jsonl", cases)
        archive.writestr("catalog.json", catalog_json)
    evidence_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    return PilotProbeReport(
        classification=classification,
        evidence_path=evidence_path,
        evidence_sha256=evidence_sha256,
        catalog_sha256=catalog_first.sha256,
        semantic_entry_count=len(catalog_first.entries),
        positive_case_count=len(first),
        negative_self_test_count=len(self_tests),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report = run_pilot_phraseology_probe(args.output_dir)
    print(
        json.dumps(
            {
                "classification": report.classification.value,
                "evidence_path": str(report.evidence_path),
                "evidence_sha256": report.evidence_sha256,
                "catalog_sha256": report.catalog_sha256,
                "semantic_entry_count": report.semantic_entry_count,
                "positive_case_count": report.positive_case_count,
                "negative_self_test_count": report.negative_self_test_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report.classification is PilotProbeClassification.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
