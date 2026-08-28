from __future__ import annotations

import json
import zipfile

from orion.mixed_composition_probe import (
    MixedProbeClassification,
    run_mixed_composition_probe,
    validate_mixed_records,
)
from orion.mixed_conversation import mixed_decomposition_tool_definition
from orion.planner_contracts import (
    PlannerToolCallsEvent,
    PlannerToolRequest,
    PlannerUsage,
)
from orion.tool_gateway_contracts import ToolArguments


class _Run:
    def __init__(self, request) -> None:  # noqa: ANN001
        self.request = request

    def next_event(self, **_kwargs):  # noqa: ANN003, ANN202
        text = self.request.interaction.text
        if "посадку" in text:
            payload = {
                "detected_input_language": "ru-RU",
                "status": "unsupported",
                "free_semantics": [],
                "free_source_text": None,
                "free_response_text": None,
                "operational_intents": [],
                "ambiguity_reason": None,
            }
        elif text == "Разрешите взлёт.":
            payload = _payload(free_source=None, free_response=None, operational=True)
        elif "Как дела" in text:
            payload = _payload(
                free_source="Добрый день! Как дела?",
                free_response="Добрый день! Всё хорошо, спасибо.",
                operational=False,
                kind="social_exchange",
            )
        else:
            source = next(
                marker
                for marker in (
                    "Добрый день!",
                    "Здравствуйте!",
                    "Доброе утро",
                    "приветствую",
                    "Добрый вечер!",
                    "рад вас слышать",
                )
                if marker in text
            )
            payload = _payload(
                free_source=source,
                free_response="Здравствуйте!",
                operational=True,
            )
        return PlannerToolCallsEvent(
            event_id=f"event-{self.request.planner_task_id}",
            calls=(
                PlannerToolRequest(
                    call_id=f"call-{self.request.planner_task_id}",
                    name=mixed_decomposition_tool_definition().name,
                    version="1.0",
                    arguments=ToolArguments(root=payload),
                ),
            ),
            usage=PlannerUsage(
                model_identifier="qwen3.6-35b-a3b",
                provider_request_ids=(f"response-{self.request.planner_task_id}",),
                provider_attempts=1,
                provider_latency_ms=10.0,
            ),
        )

    def continue_with_tool_results(self, _results) -> None:  # noqa: ANN001
        raise AssertionError("not used")

    def cancel(self) -> None:
        return None


class _Provider:
    provider_id = "fake.qwen.strict"

    def start(self, request):  # noqa: ANN001, ANN201
        return _Run(request)


def _payload(
    *,
    free_source: str | None,
    free_response: str | None,
    operational: bool,
    kind: str = "greeting",
) -> dict[str, object]:
    return {
        "detected_input_language": "ru-RU",
        "status": "classified",
        "free_semantics": [kind] if free_source is not None else [],
        "free_source_text": free_source,
        "free_response_text": free_response,
        "operational_intents": (
            ["takeoff_clearance_request"] if operational else []
        ),
        "ambiguity_reason": None,
    }


def test_probe_bundle_captures_split_atc_composition_and_all_corruptions(tmp_path) -> None:  # noqa: ANN001
    report = run_mixed_composition_probe(tmp_path, provider=_Provider())
    assert report.classification is MixedProbeClassification.PASS
    assert report.positive_case_count == 9
    assert report.negative_self_test_count == 14
    assert report.provider_request_count == 9
    assert report.provider_attempt_count == 9
    with zipfile.ZipFile(report.evidence_path) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == [
            "manifest.txt",
            "summary.json",
            "cases.jsonl",
            "catalog.json",
        ]
        summary = json.loads(archive.read("summary.json"))
        records = [
            json.loads(line)
            for line in archive.read("cases.jsonl").decode("utf-8").splitlines()
        ]
    positive = [row for row in records if row["record_type"] == "positive_case"]
    self_tests = [
        row for row in records if row["record_type"] == "negative_self_test"
    ]
    assert len(positive) == 9 and all(row["overall"] == "PASS" for row in positive)
    assert len(self_tests) == 14
    assert all(row["detected"] and row["overall"] == "PASS" for row in self_tests)
    assert summary["mixed_case_count"] == 6
    assert summary["control_case_count"] == 3
    assert summary["selected_communication_profile"] == "FAP_RUSSIAN_ATC"
    assert summary["input_language_profile_independent"] is True
    assert summary["audio_used"] is summary["dcs_used"] is summary["srs_used"] is False


def test_validator_detects_changed_duplicate_and_dropped_records() -> None:
    expected = [{"case_id": "case-1", "value": "protected", "duration_ms": 1.0}]
    assert validate_mixed_records(expected, expected) == ()
    assert validate_mixed_records(expected, []) == ("dropped:case-1",)
    assert validate_mixed_records(expected, expected * 2) == ("duplicate:case-1",)
    assert validate_mixed_records(expected, [{**expected[0], "value": "changed"}]) == (
        "changed:case-1",
    )


def test_evidence_excludes_credentials_headers_and_raw_provider_bodies(tmp_path) -> None:  # noqa: ANN001
    report = run_mixed_composition_probe(tmp_path, provider=_Provider())
    with zipfile.ZipFile(report.evidence_path) as archive:
        combined = b"".join(archive.read(name) for name in archive.namelist()).lower()
    for forbidden in (
        b"api-key",
        b"authorization",
        b"bearer ",
        b"provider request body",
        b"provider response body",
    ):
        assert forbidden not in combined
