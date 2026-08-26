from __future__ import annotations

import asyncio
import ast
import json
import threading
import zipfile
from pathlib import Path

import pytest

import orion.yandex_presentation as presentation_module
from orion.interaction_contracts import PresentationMode, SemanticResponse
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_presentation import (
    BASELINE_ROLE,
    BASELINE_VOICE,
    ProbeSelection,
    ProbeState,
    YandexPresentationAdapter,
    YandexPresentationSessionDriver,
    cases_for,
    naturalize_fidelity,
    presentation_events,
    semantic_presentation_text,
    synthetic_probe_cases,
    verbatim_fidelity,
)


class _Diagnostics:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def record(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


class _ResponsiveWebSocket:
    def __init__(
        self,
        driver_getter,  # noqa: ANN001
        *,
        fail_response: bool = False,
    ) -> None:
        self.driver_getter = driver_getter
        self.fail_response = fail_response
        self.sent: list[dict[str, object]] = []
        self.response_sequence = 0

    async def send_json(self, event: dict[str, object]) -> None:
        self.sent.append(event)
        driver = self.driver_getter()
        kind = event["type"]
        if kind == "session.update":
            output = ((event.get("session") or {}).get("audio") or {}).get("output") or {}
            driver.handle_event(
                {
                    "type": "session.updated",
                    "event_id": f"ack-{len(self.sent)}",
                    "session": {
                        "id": "yandex-session-1",
                        "audio": {"output": dict(output)},
                    },
                }
            )
        elif kind == "response.create":
            if self.fail_response:
                driver.handle_event({"type": "error", "error": {"code": "bad_request"}})
                self.fail_response = False
                return
            self.response_sequence += 1
            response_id = f"provider-response-{self.response_sequence}"
            driver.handle_event(
                {
                    "type": "response.created",
                    "event_id": f"created-{self.response_sequence}",
                    "response": {"id": response_id},
                }
            )
            case = driver._active.case  # noqa: SLF001 - deterministic protocol fake
            transcript = (
                case.semantic_response.verbatim_text
                or semantic_presentation_text(case.semantic_response)
            )
            driver.handle_event(
                {
                    "type": "response.output_audio_transcript.done",
                    "response_id": response_id,
                    "transcript": transcript,
                }
            )
            driver.handle_event(
                {
                    "type": "response.done",
                    "response": {"id": response_id, "status": "completed"},
                }
            )


def test_real_ia0_naturalize_and_verbatim_responses_build_bounded_provider_events() -> None:
    naturalize = synthetic_probe_cases()[0]
    verbatim = synthetic_probe_cases()[-1]
    assert isinstance(naturalize.semantic_response, SemanticResponse)
    assert isinstance(verbatim.semantic_response, SemanticResponse)
    assert naturalize.semantic_response.presentation_mode is PresentationMode.NATURALIZE
    assert verbatim.semantic_response.presentation_mode is PresentationMode.VERBATIM

    before_naturalize = naturalize.semantic_response.model_dump_json()
    before_verbatim = verbatim.semantic_response.model_dump_json()
    naturalize_item, naturalize_create = presentation_events(
        naturalize,
        item_event_id="item-a",
        response_event_id="response-a",
    )
    verbatim_item, verbatim_create = presentation_events(
        verbatim,
        item_event_id="item-h",
        response_event_id="response-h",
    )

    assert naturalize.semantic_response.model_dump_json() == before_naturalize
    assert verbatim.semantic_response.model_dump_json() == before_verbatim
    assert naturalize_item["type"] == verbatim_item["type"] == "conversation.item.create"
    assert naturalize_create["type"] == verbatim_create["type"] == "response.create"
    assert naturalize_create["response"]["output_modalities"] == ["audio"]
    assert len(naturalize_create["response"]["instructions"]) < 800
    assert len(verbatim_create["response"]["instructions"]) < 800


def test_presentation_input_preserves_semantic_categories_without_context_dump() -> None:
    recommendation = synthetic_probe_cases()[5].semantic_response
    text = semantic_presentation_text(recommendation)
    assert "authoritative:tanker.callsign=Texaco 1-1" in text
    assert "authoritative:tanker.distance=47 NM" in text
    assert "recommendation=Proceed to Texaco 1-1." in text
    assert "fact_origin=synthetic_probe" in text
    unavailable = semantic_presentation_text(synthetic_probe_cases()[6].semantic_response)
    assert "input:navigation.tacan=unavailable" in unavailable
    assert "latitude" not in text.casefold()
    assert "longitude" not in text.casefold()
    assert "flightcontext" not in text.casefold()
    assert "world model" not in text.casefold()


def test_synthetic_probe_contains_all_corruption_sensitive_cases_and_modes() -> None:
    cases = synthetic_probe_cases()
    assert [case.case_id for case in cases] == [
        "case-a-heading-speed",
        "case-b-callsign",
        "case-c-radio",
        "case-d-tacan",
        "case-e-laser",
        "case-f-recommendation",
        "case-g-unavailable",
        "case-h-verbatim",
    ]
    combined = "\n".join(semantic_presentation_text(case.semantic_response) for case in cases)
    for token in ("256", "241", "Colt 1-1", "251.000", "AM", "31Y", "1688", "47", "72"):
        assert token in combined
    assert [case.case_id for case in cases_for(ProbeSelection.NATURALIZE)] == [
        case.case_id for case in cases[:7]
    ]
    assert [case.case_id for case in cases_for(ProbeSelection.VERBATIM)] == [
        case.case_id for case in cases[7:]
    ]
    assert len(cases_for(ProbeSelection.FULL)) == 14


def test_fidelity_comparators_remain_sensitive_and_never_auto_pass_naturalize() -> None:
    expected = "Colt 1-1, heading 256, true airspeed 241 knots, laser code 1688."
    assert verbatim_fidelity(expected, expected) == (True, True)
    assert verbatim_fidelity(expected, expected.upper()) == (False, True)
    assert verbatim_fidelity(expected, expected.replace("1688", "1689")) == (False, False)
    response = synthetic_probe_cases()[0].semantic_response
    assert naturalize_fidelity(response, "Heading 256 degrees, true airspeed 241 knots.") == {
        "status": "REVIEW_REQUIRED",
        "tokens_preserved": True,
    }
    assert naturalize_fidelity(response, "Heading 255, speed 241.")["status"] == "FAIL"


def test_provider_json_is_confined_to_yandex_boundary_and_ia0_is_not_modified() -> None:
    module = Path(presentation_module.__file__ or "")
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "orion.interaction_contracts" in imports
    ia0 = module.with_name("interaction_contracts.py").read_text(encoding="utf-8")
    assert "yandex" not in ia0.casefold()
    assert "conversation.item.create" not in ia0
    assert "response.create" not in ia0


def test_adapter_requires_compatible_session_and_rejects_duplicate_start() -> None:
    adapter = YandexPresentationAdapter()
    with pytest.raises(ValueError, match="compatible active"):
        adapter.start(ProbeSelection.VERBATIM)
    submitted = []
    adapter.attach(yandex_session_id="session", submit=submitted.append)
    status = adapter.start(ProbeSelection.VERBATIM)
    assert status.state is ProbeState.RUNNING
    assert submitted[0].selection is ProbeSelection.VERBATIM
    with pytest.raises(ValueError, match="already running"):
        adapter.start(ProbeSelection.NATURALIZE)


def test_session_driver_correlates_cases_restores_voice_and_exports_privacy_safe_evidence(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    monkeypatch.setattr(presentation_module, "realtime_test_evidence", recorder)

    async def scenario() -> None:
        adapter = YandexPresentationAdapter()
        holder = {}
        driver = YandexPresentationSessionDriver(
            adapter,
            yandex_session_id="yandex-session-1",
            diagnostics=_Diagnostics(),
            interaction_idle=lambda: True,
        )
        holder["driver"] = driver
        websocket = _ResponsiveWebSocket(lambda: holder["driver"])
        stop = threading.Event()
        task = asyncio.create_task(driver.run(websocket, stop))
        adapter.start(ProbeSelection.VERBATIM)
        for _ in range(100):
            if adapter.status().state is ProbeState.COMPLETE:
                break
            await asyncio.sleep(0)
        assert adapter.status().state is ProbeState.COMPLETE
        assert not [event for event in websocket.sent if event["type"] == "session.update"]
        stop.set()
        await task
        driver.close()

    asyncio.run(scenario())
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        assert "ia1-summary.json" in archive.namelist()
        manifest = archive.read("manifest.txt").decode("utf-8")
        summary = json.loads(archive.read("ia1-summary.json"))
        combined = b"".join(archive.read(name) for name in archive.namelist()).lower()
    assert "format_version=3" in manifest
    assert summary["fact_origin"] == "synthetic_probe"
    case = summary["cases"][0]
    assert case["probe_case_id"] == "case-h-verbatim"
    assert case["verbatim_exact_match"] is True
    assert case["result"] == "PASS"
    for forbidden in (b"authorization", b"api-key", b"raw_audio", b"system prompt"):
        if forbidden == b"raw_audio":
            assert b"raw_audio_included=false" in combined
        else:
            assert forbidden not in combined


def test_driver_failure_is_bounded_and_restores_baseline_voice(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        presentation_module,
        "realtime_test_evidence",
        RealtimeTestEvidenceRecorder(),
    )

    async def scenario() -> None:
        adapter = YandexPresentationAdapter()
        holder = {}
        driver = YandexPresentationSessionDriver(
            adapter,
            yandex_session_id="yandex-session-1",
            diagnostics=_Diagnostics(),
            interaction_idle=lambda: True,
        )
        holder["driver"] = driver
        websocket = _ResponsiveWebSocket(lambda: holder["driver"], fail_response=True)
        stop = threading.Event()
        task = asyncio.create_task(driver.run(websocket, stop))
        adapter.start(ProbeSelection.VOICE)
        for _ in range(100):
            if adapter.status().state is ProbeState.FAILED:
                break
            await asyncio.sleep(0)
        assert adapter.status().state is ProbeState.FAILED
        assert websocket.sent[-1]["type"] == "session.update"
        assert websocket.sent[-1]["session"]["audio"]["output"]["voice"] == BASELINE_VOICE
        stop.set()
        await task
        driver.close()

    asyncio.run(scenario())


def test_launcher_contains_only_one_compact_existing_window_probe_block() -> None:
    source = (Path(__file__).parents[1] / "orion" / "launcher_cloud_voice_sections.py").read_text(
        encoding="utf-8"
    )
    assert source.count('text="PRESENTATION PROBE"') == 1
    assert source.count('text="RUN PRESENTATION PROBE"') == 1
    assert '("NATURALIZE", "VERBATIM", "VOICE", "STYLE", "FULL")' in source
    assert "Tk(" not in source
