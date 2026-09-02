from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_arch_guard_ag2 import _build  # type: ignore[import-not-found]
from tools.orion_arch_guard.cli import main
from tools.orion_arch_guard.guard import (
    ArchitectureGate,
    ArchitectureGuard,
    CapabilityIntent,
    GuardMode,
    PreflightInput,
)
from tools.orion_arch_guard.guard_rules import AG3_RULESET_VERSION

HEAD = "a" * 40
NOW = datetime(2026, 9, 2, 12, 34, 56, tzinfo=timezone.utc)


def _request(
    title: str,
    *,
    mode: GuardMode = GuardMode.FULL,
    description: str = "",
    proposed: str = "",
    capabilities: tuple[str, ...] = (),
    constraints: tuple[str, ...] = (),
) -> PreflightInput:
    return PreflightInput(
        mode=mode,
        task_title=title,
        task_description=description,
        proposed_change=proposed,
        explicit_capabilities=capabilities,
        current_head=HEAD,
        user_constraints=constraints,
    )


def _run(tmp_path: Path, request: PreflightInput):  # noqa: ANN202
    database, _result = _build(tmp_path)
    guard = ArchitectureGuard(database, reports_dir=tmp_path / "reports", now=lambda: NOW)
    try:
        return guard.preflight(request, store=False), database
    finally:
        guard.close()


def _types(result: dict[str, object], key: str) -> set[str]:
    return {str(item["type"]) for item in result[key]}  # type: ignore[index,union-attr]


@pytest.mark.parametrize("mode", list(GuardMode))
def test_full_standard_light_remain_bounded_for_test_only_change(
    tmp_path: Path, mode: GuardMode
) -> None:
    report, _database = _run(
        tmp_path,
        _request(
            "Add a bounded deterministic test for UDP7082 without changing ownership or architecture",
            mode=mode,
            capabilities=("UDP7082",),
        ),
    )
    assert report.result["mode_effective"] == mode.value
    assert report.result["gate"] == ArchitectureGate.PASS.value
    assert "D71" in {
        item["decision_id"] for item in report.result["decisions"]["CURRENT"]
    }
    assert report.result["evidence_reuse"]["existing_tests_reusable"] is True


def test_standard_escalates_to_full_for_radio_ownership_change(tmp_path: Path) -> None:
    report, _database = _run(
        tmp_path,
        _request(
            "Replace UDP7082 EOU with packet-gap detection",
            mode=GuardMode.STANDARD,
        ),
    )
    assert report.result["mode_effective"] == GuardMode.FULL.value
    assert {"PTT_OWNER_CHANGED", "EOU_OWNER_CHANGED"} <= _types(
        report.result, "ownership_drift"
    )
    assert report.result["gate"] == ArchitectureGate.BLOCK.value


def test_windows_launcher_negated_srs_constraints_do_not_change_radio_transport(
    tmp_path: Path,
) -> None:
    report, _database = _run(
        tmp_path,
        _request(
            "ORION Development Console Windows launch entry point",
            description=(
                "Provide a normal no-terminal Windows launch entry for the completed "
                "dev-only Development Console, reusing its existing Tk UI and approved "
                "ORION icon while preserving repository-current behavior and all "
                "production lifecycle boundaries."
            ),
            proposed=(
                "Evaluate and implement the smallest history-compatible Windows entry "
                "mechanism, likely a repository-resolving pythonw wrapper plus "
                "deterministic shortcut creation support, only if the Guard confirms it. "
                "Do not freeze or package production ORION, do not duplicate the Console, "
                "and do not start Core, Launcher, DCS, SRS, providers, or microphone."
            ),
            constraints=(
                "Run from any working directory with a useful visible failure when "
                "repository or development runtime is missing.",
                "Normal launch must show one GUI window, use branding/orion.ico, and "
                "require no terminal.",
                "Prefer repository-current execution without frozen-executable rebuild "
                "churn.",
                "Any real shortcut mutation must be explicitly reported and remain easy "
                "to remove or recreate.",
                "Preserve all unrelated untracked/generated artifacts and the pending "
                "unsaved checkpoint.",
            ),
        ),
    )
    result = report.result
    assert "RADIO_TRANSPORT_CHANGED" not in _types(result, "ownership_drift")
    assert "DUPLICATE_FIELD_PROVEN_RADIO_STACK" not in _types(result, "conflicts")
    assert result["gate"] == ArchitectureGate.PASS.value
    srs = next(
        item for item in result["affected_capabilities"] if item["capability_id"] == "SRS"
    )
    assert CapabilityIntent.PROHIBITED_ACTION.value in srs["intents"]
    assert srs["proposed_change"] is False


@pytest.mark.parametrize(
    ("title", "capability", "intent"),
    (
        ("Do not add Whisper.", "STT", CapabilityIntent.PROHIBITED_ACTION),
        (
            "Do not replace SpeechKit.",
            "SPEECHKIT_STT",
            CapabilityIntent.PROHIBITED_ACTION,
        ),
        (
            "Preserve Core-owned phraseology.",
            "PHRASEOLOGY",
            CapabilityIntent.REQUIRED_PRESERVATION,
        ),
        ("Do not modify UDP7082.", "UDP7082", CapabilityIntent.PROHIBITED_ACTION),
        ("Do not change Qwen.", "QWEN_PLANNER", CapabilityIntent.PROHIBITED_ACTION),
    ),
)
def test_negated_capability_mentions_are_constraints_not_mutations(
    tmp_path: Path,
    title: str,
    capability: str,
    intent: CapabilityIntent,
) -> None:
    report, _database = _run(tmp_path, _request(title))
    result = report.result
    assert result["ownership_drift"] == []
    assert result["conflicts"] == []
    assert result["gate"] == ArchitectureGate.PASS.value
    match = next(
        item
        for item in result["affected_capabilities"]
        if item["capability_id"] == capability
    )
    assert intent.value in match["intents"]
    assert match["proposed_change"] is False


def test_task_intent_model_distinguishes_all_required_categories(tmp_path: Path) -> None:
    report, _database = _run(
        tmp_path,
        _request(
            "Create a Development Console launcher entry.",
            description="Preserve existing RadioRouter ownership. Core is context only.",
            proposed="Inspect Qwen in read-only mode.",
            constraints=(
                "SRS is out of scope.",
                "Do not modify UDP7082.",
            ),
        ),
    )
    counts = report.result["task_intent"]["intent_counts"]
    assert all(counts[intent.value] >= 1 for intent in CapabilityIntent)
    assert report.result["gate"] == ArchitectureGate.PASS.value


def test_positive_srs_transport_change_remains_blocked(tmp_path: Path) -> None:
    report, _database = _run(
        tmp_path,
        _request("Build a new SRS transport for the next ATC feature."),
    )
    result = report.result
    assert "RADIO_TRANSPORT_CHANGED" in _types(result, "ownership_drift")
    assert "DUPLICATE_FIELD_PROVEN_RADIO_STACK" in _types(result, "conflicts")
    assert result["gate"] == ArchitectureGate.BLOCK.value
    srs = next(
        item for item in result["affected_capabilities"] if item["capability_id"] == "SRS"
    )
    assert srs["proposed_change"] is True


def test_positive_radio_transport_change_is_not_hidden_by_negated_srs_clause(
    tmp_path: Path,
) -> None:
    report, _database = _run(
        tmp_path,
        _request("Replace radio transport, but do not change SRS."),
    )
    result = report.result
    assert "RADIO_TRANSPORT_CHANGED" in _types(result, "ownership_drift")
    assert "DUPLICATE_FIELD_PROVEN_RADIO_STACK" in _types(result, "conflicts")
    assert result["gate"] == ArchitectureGate.BLOCK.value


def test_yandex_qwen_previous_best_requires_user_decision(tmp_path: Path) -> None:
    report, _database = _run(
        tmp_path,
        _request(
            "Implement natural response to live DCS aircraft identity",
            proposed="Qwen Planner formulation",
        ),
    )
    result = report.result
    implementations = {
        item["implementation_id"] for item in result["implementation_records"]
    }
    assert {
        "STAGE6A_FLIGHTCONTEXT_REALTIME",
        "CURRENT_QWEN_INFORMATIONAL_FORMULATION",
        "CURRENT_AIRCRAFT_IDENTITY_QUERY",
    } <= implementations
    assert {"PRESENTATION_OWNER_CHANGED", "SESSION_MODEL_CHANGED"} <= _types(
        result, "ownership_drift"
    )
    assert result["performance"]["performance_regression_risk"] == "MAJOR"
    assert result["performance"]["metric_boundary_comparability"] == "PRESERVED"
    assert result["previous_best"]["hybrid_reuse_possible"] is True
    assert {
        "PERSISTENT_REALTIME_SESSION",
        "CORE_FACT_BINDING",
        "PLACEHOLDER_FACT_VALIDATION",
    } <= set(result["previous_best"]["previous_best_mechanisms"])
    assert result["gate"] == ArchitectureGate.USER_DECISION_REQUIRED.value
    assert {"D40", "D71", "D72"} <= {
        item["decision_id"] for item in result["decisions"]["CURRENT"]
    }


@pytest.mark.parametrize(
    ("title", "conflict", "expected_implementation"),
    (
        (
            "Replace UDP7082 EOU with packet-gap detection",
            "REINTRODUCES_SUPERSEDED_EOU",
            "UDP7082_AUTHORITATIVE_EOU",
        ),
        (
            "Restore four manual Free Aviation RU EN modes",
            "REINTRODUCES_SUPERSEDED_LANGUAGE_MODES",
            "HARD_FOUR_LANGUAGE_MODES",
        ),
        (
            "Add Whisper fallback",
            "REINTRODUCES_EXPLICITLY_REMOVED_STT",
            "WHISPER_STT_WORKER",
        ),
        (
            "Let Qwen naturally rewrite protected ATC clearance phraseology",
            "PROTECTED_WORDING_AUTHORITY_REGRESSION",
            "OSU_PROTECTED_PHRASEOLOGY",
        ),
        (
            "Limit production Phraseology KB to 20-30 phrases",
            "REJECTED_PRODUCT_KB_LIMIT",
            "PILOT_PHRASEOLOGY_TEST_CORPUS",
        ),
        (
            "Add manual Launcher callsign field as authoritative identity",
            "MANUAL_CALLSIGN_FACT_AUTHORITY",
            None,
        ),
        (
            "Build a new SRS transport for next ATC feature",
            "DUPLICATE_FIELD_PROVEN_RADIO_STACK",
            "UDP7082_AUTHORITATIVE_EOU",
        ),
    ),
)
def test_mandatory_block_regressions(
    tmp_path: Path,
    title: str,
    conflict: str,
    expected_implementation: str | None,
) -> None:
    report, _database = _run(tmp_path, _request(title))
    result = report.result
    assert result["gate"] == ArchitectureGate.BLOCK.value
    assert conflict in _types(result, "conflicts")
    if expected_implementation:
        assert expected_implementation in {
            item["implementation_id"] for item in result["implementation_records"]
        }


def test_incomplete_history_wins_over_other_gate_results(tmp_path: Path) -> None:
    database, _result = _build(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute("UPDATE sources SET availability='UNAVAILABLE', exists_flag=0")
    connection.commit()
    connection.close()
    guard = ArchitectureGuard(database, reports_dir=tmp_path / "reports", now=lambda: NOW)
    try:
        report = guard.preflight(
            _request("Replace UDP7082 EOU with packet-gap detection"), store=False
        )
    finally:
        guard.close()
    assert report.result["history_coverage"]["architecture_critical_missing"]
    assert report.result["gate"] == ArchitectureGate.INCOMPLETE_HISTORY.value


def test_report_is_deterministic_machine_readable_private_and_persisted(
    tmp_path: Path,
) -> None:
    database, _result = _build(tmp_path)
    reports_dir = tmp_path / "reports"
    request = _request(
        "Add bounded test credential=DO_NOT_PERSIST_123456789",
        capabilities=("UDP7082",),
    )
    guard = ArchitectureGuard(database, reports_dir=reports_dir, now=lambda: NOW)
    try:
        first = guard.preflight(request, store=False)
        second = guard.preflight(request, store=False)
        stored = guard.preflight(request, store=True)
    finally:
        guard.close()

    assert first.result["logical_signature"] == second.result["logical_signature"]
    assert first.result["gate"] == second.result["gate"]
    assert stored.json_path and stored.json_path.is_file()
    assert stored.human_path and stored.human_path.is_file()
    encoded = stored.json_path.read_text(encoding="utf-8")
    assert "DO_NOT_PERSIST" not in encoded
    assert "[REDACTED_CREDENTIAL]" in encoded
    parsed = json.loads(encoded)
    assert parsed["report_id"] == (
        "AG-20260902-123456-"
        + parsed["report_id"].split("-")[3]
        + f"-aaaaaaa-r{AG3_RULESET_VERSION}"
    )
    assert parsed["primary_evidence"]
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM guard_runs").fetchone()[0] == 1
    finally:
        connection.close()


def test_preflight_cli_returns_machine_json(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    database, _result = _build(tmp_path)
    assert (
        main(
            [
                "preflight",
                "--mode",
                "LIGHT",
                "--task",
                "Add bounded test for UDP7082 without changing architecture",
                "--capability",
                "UDP7082",
                "--head",
                HEAD,
                "--database",
                str(database),
                "--reports-dir",
                str(tmp_path / "reports"),
                "--json",
                "--no-store",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["gate"] == ArchitectureGate.PASS.value
    assert output["ruleset_version"] == AG3_RULESET_VERSION
    assert output["primary_evidence"]
