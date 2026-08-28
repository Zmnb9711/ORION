from __future__ import annotations

import json
import threading
import time
import zipfile
from pathlib import Path

import orion.live_golden_conversation as live_module

from orion.communication_contracts import CommunicationDomain
from orion.live_golden_conversation import (
    LIVE_GOLDEN_CORPUS,
    LiveGoldenAcousticReview,
    LiveGoldenConversationService,
    LiveGoldenRuntimeContext,
    LiveGoldenState,
)
from orion.mixed_conversation import mixed_decomposition_tool_definition
from orion.planner_contracts import (
    PlannerToolCallsEvent,
    PlannerToolRequest,
    PlannerUsage,
)
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.srs_radio_adapter import SrsAdapterRuntime
from orion.srs_radio_transport import SrsState
from orion.tool_gateway_contracts import ToolArguments


class _Run:
    def __init__(self, payload: dict[str, object], *, gate: threading.Event | None = None) -> None:
        self.payload = payload
        self.gate = gate

    def next_event(self, **_kwargs):  # noqa: ANN003, ANN202
        if self.gate is not None:
            self.gate.wait(2)
        return PlannerToolCallsEvent(
            event_id="live-golden-event",
            calls=(
                PlannerToolRequest(
                    call_id="live-golden-call",
                    name=mixed_decomposition_tool_definition().name,
                    version="1.0",
                    arguments=ToolArguments(root=self.payload),
                ),
            ),
            usage=PlannerUsage(
                model_identifier="qwen3.6-35b-a3b",
                provider_request_ids=("qwen-response-1",),
                provider_attempts=1,
                provider_latency_ms=12.0,
            ),
        )

    def continue_with_tool_results(self, _results) -> None:  # noqa: ANN001
        raise AssertionError("Live Golden decomposition never continues")

    def cancel(self) -> None:
        return None


class _Provider:
    provider_id = "fake.qwen"

    def __init__(self, *, gate: threading.Event | None = None) -> None:
        self.gate = gate
        self.requests = []

    def start(self, request):  # noqa: ANN001, ANN201
        self.requests.append(request)
        text = request.interaction.text
        pure_conversation = "Как дела" in text
        pure_operational = text.strip() == "Разрешите взлёт."
        payload = {
            "detected_input_language": "ru-RU",
            "status": "classified",
            "free_semantics": [] if pure_operational else ["greeting"],
            "free_source_text": None if pure_operational else "Добрый день",
            "free_response_text": None if pure_operational else "Добрый день!",
            "operational_intents": (
                [] if pure_conversation else ["takeoff_clearance_request"]
            ),
            "ambiguity_reason": None,
        }
        return _Run(payload, gate=self.gate)


class _SpeechKit:
    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *_args):  # noqa: ANN002, ANN204
        return None

    async def synthesize(self, case, _api_key, **_kwargs):  # noqa: ANN001, ANN202
        assert "Viper 2-1" in case.finalized_text or "Добрый день" in case.finalized_text
        return bytes(4_800), case.finalized_text


class _Endpoint:
    def __init__(self) -> None:
        self.suppression: list[bool] = []
        self.transmissions: list[dict[str, object]] = []

    def set_provider_output_suppressed(self, suppressed: bool) -> None:
        self.suppression.append(suppressed)

    def srs_adapter_runtime(self) -> SrsAdapterRuntime:
        return SrsAdapterRuntime(
            state=SrsState.READY,
            endpoint_started=True,
            radio_registered=True,
            udp_registered=True,
            frequency_hz=251_000_000.0,
            modulation=0,
            bot_name="ORION SRS",
            coalition=2,
            failed=False,
        )

    def transmit_finalized_audio(
        self,
        response_id: str,
        pcm44: bytes,
        timeout_s: float,
        **fields,
    ) -> dict[str, float | int]:  # noqa: ANN003
        self.transmissions.append(
            {
                "response_id": response_id,
                "pcm": pcm44,
                "timeout_s": timeout_s,
                **fields,
            }
        )
        return {
            "queue_to_first_tx_ms": 2.0,
            "queue_to_complete_ms": 102.0,
            "frame_count": 5,
            "duration_ms": 100.0,
        }


def _wait_for(service: LiveGoldenConversationService, state: LiveGoldenState) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if service.status().state is state:
            return
        time.sleep(0.01)
    raise AssertionError(f"Live Golden did not reach {state}: {service.status()}")


def _service(
    tmp_path: Path,
    monkeypatch,
    *,
    gate: threading.Event | None = None,
) -> tuple[LiveGoldenConversationService, _Endpoint, RealtimeTestEvidenceRecorder]:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(
        provider="yandex",
        transport="srs",
        build_sha="9f38d449",
        build_branch="dev/adr004-post-389",
        build_version="0.2.0",
    )
    monkeypatch.setattr(live_module, "realtime_test_evidence", recorder)
    monkeypatch.setattr(live_module, "normalize_speechkit_pcm", lambda pcm: pcm)
    provider = _Provider(gate=gate)
    runner = live_module.LiveGoldenCaseRunner(
        provider_factory=lambda _config: provider,
        speechkit_factory=_SpeechKit,
    )
    service = LiveGoldenConversationService(runner=runner)
    endpoint = _Endpoint()
    service.attach(
        LiveGoldenRuntimeContext(
            api_key="memory-only-secret",
            folder_id="folder-id",
            endpoint=endpoint,
            main_session_id="yandex-main-session",
        )
    )
    return service, endpoint, recorder


def test_real_transcript_runs_one_qwen_local_protected_composition_and_one_radio_tx(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    service, endpoint, recorder = _service(tmp_path, monkeypatch)
    status = service.start(capture_audio=True)
    assert status.state is LiveGoldenState.WAITING_INPUT
    assert status.next_prompt == "Добрый день! Разрешите взлёт."
    assert endpoint.suppression == [True]

    service.accept_transcript(
        "Добрый день! Разрешите взлёт.",
        "turn_001",
        "event-user",
        "item-user",
        time.monotonic() - 0.02,
    )
    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    assert len(endpoint.transmissions) == 1
    assert endpoint.transmissions[0]["source_domain"] is CommunicationDomain.ATC
    assert endpoint.transmissions[0]["entity_id"] == "orion.live-golden"

    reviewed = service.review(LiveGoldenAcousticReview.CLEAR)
    assert reviewed.state is LiveGoldenState.WAITING_INPUT
    assert reviewed.case_id == "mixed-ru-2"
    service.stop()
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        summary = json.loads(archive.read("live-golden-summary.json"))
        session = archive.read("session-summary.txt").decode()
        names = archive.namelist()
        combined = b"".join(archive.read(name) for name in names)
    case = summary["runs"][0]["cases"][0]
    assert case["qwen"]["provider_response_ids"] == ["qwen-response-1"]
    assert case["qwen"]["reasoning_passes_after_operational_truth"] == 0
    assert case["protected_fragment"] == "Viper 2-1, полоса 07/25, взлёт разрешён."
    assert case["final_composed_text"] == (
        "Добрый день! Viper 2-1, полоса 07/25, взлёт разрешён."
    )
    assert case["final_composed_text"].count(case["protected_fragment"]) == 1
    assert case["radio"]["frame_count"] == 5
    assert case["acoustic_review"] == "clear"
    assert "live-golden-audio/mixed-ru-1.wav" in names
    assert "orion_build_sha=9f38d449" in session
    assert "orion_build_branch=dev/adr004-post-389" in session
    assert b"memory-only-secret" not in combined


def test_duplicate_transcript_and_review_gate_cannot_create_two_transmissions(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    service, endpoint, recorder = _service(tmp_path, monkeypatch)
    service.start(capture_audio=False)
    for _ in range(2):
        service.accept_transcript(
            "Добрый день! Разрешите взлёт.",
            "turn_001",
            "event-user",
            "item-user",
            time.monotonic(),
        )
    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    service.accept_transcript(
        "Здравствуйте! Можно взлетать?",
        "turn_002",
        "event-2",
        "item-2",
        time.monotonic(),
    )
    time.sleep(0.05)
    assert len(endpoint.transmissions) == 1
    service.stop()
    recorder.stop_and_export()


def test_six_mixed_cases_and_two_controls_run_without_configuration_edits(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    service, endpoint, recorder = _service(tmp_path, monkeypatch)
    service.start(capture_audio=False)
    for index, case in enumerate(LIVE_GOLDEN_CORPUS, start=1):
        current = service.status()
        assert current.case_number == index
        assert current.next_prompt == case.prompt
        service.accept_transcript(
            case.prompt,
            f"turn_{index:03d}",
            f"event-{index}",
            f"item-{index}",
            time.monotonic(),
        )
        _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
        service.review(LiveGoldenAcousticReview.CLEAR)
    assert service.status().state is LiveGoldenState.COMPLETE
    assert service.status().completed_cases == service.status().reviewed_cases == 8
    assert len(endpoint.transmissions) == 8
    assert [item["source_domain"] for item in endpoint.transmissions] == [
        *([CommunicationDomain.ATC] * 7),
        CommunicationDomain.GENERAL,
    ]
    assert endpoint.suppression == [True, False]
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        summary = json.loads(archive.read("live-golden-summary.json"))
    records = summary["runs"][0]["cases"]
    assert len(records) == 8
    assert sum(record["primary"] for record in records) == 6
    assert all(record["internal_result"] == "PASS" for record in records)
    assert all(record["acoustic_review"] == "clear" for record in records)


def test_operator_stop_while_qwen_is_in_flight_prevents_stale_speechkit_and_radio_tx(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    gate = threading.Event()
    service, endpoint, recorder = _service(tmp_path, monkeypatch, gate=gate)
    service.start(capture_audio=False)
    service.accept_transcript(
        "Добрый день! Разрешите взлёт.",
        "turn_001",
        "event-user",
        "item-user",
        time.monotonic(),
    )
    _wait_for(service, LiveGoldenState.PROCESSING)
    service.stop()
    gate.set()
    time.sleep(0.1)
    assert endpoint.transmissions == []
    assert endpoint.suppression == [True, False]
    recorder.stop_and_export()


def test_start_fails_closed_without_test_evidence_or_full_srs_readiness(
    monkeypatch,
) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder()
    monkeypatch.setattr(live_module, "realtime_test_evidence", recorder)
    service = LiveGoldenConversationService()
    endpoint = _Endpoint()
    service.attach(
        LiveGoldenRuntimeContext(
            api_key="secret",
            folder_id="folder-id",
            endpoint=endpoint,
            main_session_id="session",
        )
    )
    try:
        service.start(capture_audio=False)
    except ValueError as exc:
        assert "Test Evidence" in str(exc)
    else:
        raise AssertionError("Live Golden started without explicit evidence")
