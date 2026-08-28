from __future__ import annotations

import json
import zipfile

from orion.golden_takeoff_probe import (
    GoldenProbeClassification,
    run_golden_takeoff_probe,
    validate_golden_records,
)


def test_probe_exports_complete_deterministic_chain_and_self_tests(tmp_path) -> None:  # noqa: ANN001
    report = run_golden_takeoff_probe(tmp_path)
    assert report.classification is GoldenProbeClassification.PASS
    assert report.scenario_count == 18
    assert report.negative_self_test_count == 11
    assert len(report.evidence_sha256) == 64
    assert len(report.catalog_sha256) == 64

    with zipfile.ZipFile(report.evidence_path) as archive:
        assert archive.namelist() == [
            "manifest.txt",
            "summary.json",
            "cases.jsonl",
            "catalog.json",
        ]
        manifest = archive.read("manifest.txt").decode("utf-8")
        summary = json.loads(archive.read("summary.json"))
        records = [
            json.loads(line)
            for line in archive.read("cases.jsonl").decode("utf-8").splitlines()
        ]
    cases = [row for row in records if row["record_type"] == "golden_case"]
    self_tests = [
        row for row in records if row["record_type"] == "negative_self_test"
    ]
    assert len(cases) == 18
    assert len(self_tests) == 11
    assert all(row["overall"] == "PASS" for row in cases)
    assert all(row["detected"] and row["overall"] == "PASS" for row in self_tests)
    assert summary["fresh_vertical_repeat_deterministic"] is True
    assert summary["approved_variants_same_canonical_intent"] is True
    assert summary["different_wording_same_permitted_decision"] is True
    assert summary["ru_en_canonical_decision_equivalent"] is True
    assert summary["unavailable_values_not_fabricated"] is True
    assert summary["independent_validation_issues"] == []
    assert "classification=GOLDEN VERTICAL PASS" in manifest
    assert "network_used=false" in manifest
    assert "provider_used=false" in manifest
    assert "dcs_used=false" in manifest
    assert "srs_used=false" in manifest
    assert "credentials_included=false" in manifest


def test_fresh_probe_runs_preserve_semantic_identity(tmp_path) -> None:  # noqa: ANN001
    first = run_golden_takeoff_probe(tmp_path / "first")
    second = run_golden_takeoff_probe(tmp_path / "second")
    assert first.classification is second.classification is GoldenProbeClassification.PASS
    assert first.catalog_sha256 == second.catalog_sha256
    with (
        zipfile.ZipFile(first.evidence_path) as first_zip,
        zipfile.ZipFile(second.evidence_path) as second_zip,
    ):
        first_rows = first_zip.read("cases.jsonl").decode("utf-8").splitlines()[:18]
        second_rows = second_zip.read("cases.jsonl").decode("utf-8").splitlines()[:18]
    canonical = lambda rows: [  # noqa: E731
        {
            key: value
            for key, value in json.loads(row).items()
            if key not in {"duration_ms", "validation_assertions"}
        }
        for row in rows
    ]
    assert canonical(first_rows) == canonical(second_rows)


def test_validator_detects_duplicate_drop_and_chain_mutation() -> None:
    expected = [
        {
            "record_type": "golden_case",
            "case_id": "case-1",
            "actual_status": "granted",
            "rendered_text": "Viper 2-1, runway 07/25, cleared for takeoff.",
            "duration_ms": 1.0,
            "validation_assertions": {"complete": True},
        }
    ]
    assert validate_golden_records(expected, expected) == ()
    assert validate_golden_records(expected, []) == ("dropped:case-1",)
    assert validate_golden_records(expected, expected * 2) == ("duplicate:case-1",)
    changed = [{**expected[0], "actual_status": "hold"}]
    assert validate_golden_records(expected, changed) == ("changed:case-1",)


def test_evidence_has_no_provider_credential_or_transport_payload(tmp_path) -> None:  # noqa: ANN001
    report = run_golden_takeoff_probe(tmp_path)
    with zipfile.ZipFile(report.evidence_path) as archive:
        combined = b"".join(archive.read(name) for name in archive.namelist()).lower()
    for forbidden in (
        b"api-key",
        b"authorization",
        b"bearer ",
        b"speechkit",
        b"websocket",
        b"srs tx",
    ):
        assert forbidden not in combined
