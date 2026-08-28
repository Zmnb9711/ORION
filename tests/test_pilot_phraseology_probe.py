from __future__ import annotations

import json
import zipfile

from orion.pilot_phraseology_probe import (
    PilotProbeClassification,
    run_pilot_phraseology_probe,
    validate_probe_records,
)


def test_offline_probe_exports_complete_machine_verifiable_bundle(tmp_path) -> None:  # noqa: ANN001
    report = run_pilot_phraseology_probe(tmp_path)
    assert report.classification is PilotProbeClassification.PASS
    assert report.semantic_entry_count == 25
    assert report.positive_case_count == 50
    assert report.negative_self_test_count == 12
    assert report.evidence_path.parent == tmp_path
    assert len(report.evidence_sha256) == 64

    with zipfile.ZipFile(report.evidence_path) as archive:
        assert archive.namelist() == [
            "manifest.txt",
            "summary.json",
            "cases.jsonl",
            "catalog.json",
        ]
        manifest = archive.read("manifest.txt").decode("utf-8")
        summary = json.loads(archive.read("summary.json"))
        catalog = json.loads(archive.read("catalog.json"))
        records = [
            json.loads(line)
            for line in archive.read("cases.jsonl").decode("utf-8").splitlines()
        ]

    positives = [
        record for record in records if record["record_type"] == "positive_case"
    ]
    self_tests = [
        record for record in records if record["record_type"] == "negative_self_test"
    ]
    assert len(positives) == summary["expected_positive_result_count"] == 50
    assert len(self_tests) == summary["negative_self_test_count"] == 12
    assert all(record["overall"] == "PASS" for record in positives)
    assert all(
        record["detected"] and record["overall"] == "PASS" for record in self_tests
    )
    assert summary["fresh_resolver_repeat_deterministic"] is True
    assert summary["catalog_hash_stable"] is True
    assert summary["ru_en_semantic_equivalence"] is True
    assert summary["independent_validation_issues"] == []
    assert catalog["catalog_sha256"] == report.catalog_sha256
    assert len(catalog["entries"]) == 25
    assert "classification=PILOT PASS" in manifest
    assert "network_used=false" in manifest
    assert "credentials_included=false" in manifest


def test_probe_catalog_identity_is_stable_across_fresh_runs(tmp_path) -> None:  # noqa: ANN001
    first = run_pilot_phraseology_probe(tmp_path / "first")
    second = run_pilot_phraseology_probe(tmp_path / "second")
    assert (
        first.classification is second.classification is PilotProbeClassification.PASS
    )
    assert first.catalog_sha256 == second.catalog_sha256
    with (
        zipfile.ZipFile(first.evidence_path) as first_zip,
        zipfile.ZipFile(second.evidence_path) as second_zip,
    ):
        assert first_zip.read("catalog.json") == second_zip.read("catalog.json")


def test_independent_validator_detects_duplicate_drop_and_semantic_change() -> None:
    expected = [
        {
            "case_id": "case-1",
            "catalog_sha256": "a" * 64,
            "communication_profile": "NATO_MILITARY",
            "domain": "navigation",
            "language": "en-US",
            "semantic_meaning": "navigation.heading",
            "semantic_status": "available",
            "semantic_polarity": None,
            "resolution_status": "rendered",
            "input_protected_values": [{"value": 137, "unit": "deg"}],
            "input_units": {"heading": "deg"},
            "provenance": [{"source": "fixture"}],
            "expected_entry_id": "navigation-heading",
            "selected_entry_id": "navigation-heading",
            "resolved_slots": [{"value": "137", "unit": "deg"}],
            "rendered_text": "Heading 137 degrees.",
            "expected_protected_semantic_values": [{"value": 137, "unit": "deg"}],
            "overall": "PASS",
            "typed_failure": None,
        }
    ]
    assert validate_probe_records(expected, expected) == ()
    assert any(
        issue.startswith("duplicate:")
        for issue in validate_probe_records(expected, expected * 2)
    )
    assert any(
        issue.startswith("dropped:") for issue in validate_probe_records(expected, [])
    )
    changed = [{**expected[0], "selected_entry_id": "navigation-speed"}]
    assert "changed:case-1:selected_entry_id" in validate_probe_records(
        expected, changed
    )


def test_evidence_contains_no_provider_or_credential_payload(tmp_path) -> None:  # noqa: ANN001
    report = run_pilot_phraseology_probe(tmp_path)
    with zipfile.ZipFile(report.evidence_path) as archive:
        combined = b"".join(archive.read(name) for name in archive.namelist()).lower()
    for forbidden in (
        b"api-key",
        b"authorization",
        b"bearer ",
        b"speechkit",
        b"websocket",
    ):
        assert forbidden not in combined
