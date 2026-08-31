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
    LiveGoldenPttCoordinator,
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
from orion.radio_streaming import StreamingPcmEvent
from orion.realtime_audio_transport import (
    FinalizedUserUtterance,
    RealtimeTranscriptSegment,
)
from orion.srs_radio_adapter import SrsAdapterRuntime
from orion.srs_radio_transport import SrsState
from orion.tool_gateway_contracts import ToolArguments
from orion.yandex_speechkit_streaming_tts import SpeechKitTtsOutputMode


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


class _StreamingFailureBeforeTx:
    async def stream(
        self,
        _text: str,
        _api_key: str,
        *,
        response_id: str,
        cancelled,
    ):  # noqa: ANN001, ANN202
        assert not cancelled()
        yield StreamingPcmEvent(
            response_id=response_id,
            pcm=b"",
            sample_rate_hz=48_000,
            channels=1,
            sample_width_bytes=2,
            chunk_index=0,
            error="bounded fake provider failure",
        )


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
    tts_output_mode: SpeechKitTtsOutputMode = SpeechKitTtsOutputMode.REST_BUFFERED,
    streaming_speechkit_factory=None,  # noqa: ANN001
) -> tuple[
    LiveGoldenConversationService,
    _Endpoint,
    RealtimeTestEvidenceRecorder,
    _Provider,
]:  # noqa: ANN001
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
        streaming_speechkit_factory=(
            streaming_speechkit_factory or live_module.SpeechKitStreamingTtsClient
        ),
    )
    service = LiveGoldenConversationService(runner=runner, ptt_settle_seconds=0.01)
    endpoint = _Endpoint()
    service.attach(
        LiveGoldenRuntimeContext(
            api_key="memory-only-secret",
            folder_id="folder-id",
            endpoint=endpoint,
            main_session_id="yandex-main-session",
            tts_output_mode=tts_output_mode,
        )
    )
    return service, endpoint, recorder, provider


def test_streaming_failure_before_radio_falls_back_once_to_buffered_rest(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    service, endpoint, recorder, _provider = _service(
        tmp_path,
        monkeypatch,
        tts_output_mode=SpeechKitTtsOutputMode.STREAMING_V3,
        streaming_speechkit_factory=_StreamingFailureBeforeTx,
    )
    service.start(capture_audio=False)
    service.input_transmission_started("srs-fallback-ptt", 0)
    service.accept_transcript_segment(
        _segment("Добрый день Разрешите взлёт", "fallback-item", 0, 900)
    )
    service.input_transmission_completed("srs-fallback-ptt", 1_000)
    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    assert len(endpoint.transmissions) == 1
    service.stop()
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode("utf-8").splitlines()
        ]
        summary = json.loads(archive.read("live-golden-summary.json"))
    assert sum(
        event["event"] == "speechkit_stream_tts_rest_fallback"
        for event in events
    ) == 1
    case = summary["runs"][0]["cases"][0]
    assert case["speechkit"]["streaming_rest_fallback"] is True
    assert case["speechkit"]["output_mode"] == "speechkit_rest"


def _segment(
    text: str,
    item: str,
    start_ms: int,
    end_ms: int,
    *,
    stopped_at: float | None = None,
) -> RealtimeTranscriptSegment:
    return RealtimeTranscriptSegment(
        transcript=text,
        turn_id=f"provider-{item}",
        event_id=f"event-{item}",
        provider_item_id=item,
        speech_stopped_at=(time.monotonic() if stopped_at is None else stopped_at),
        provider_audio_start_ms=start_ms,
        provider_audio_end_ms=end_ms,
    )


def _wait_for_emissions(values: list[tuple[object, ...]], count: int) -> None:
    deadline = time.monotonic() + 1
    while len(values) < count and time.monotonic() < deadline:
        time.sleep(0.005)
    assert len(values) == count


def test_split_provider_segments_dispatch_one_complete_live_golden_case(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    service, endpoint, recorder, provider = _service(tmp_path, monkeypatch)
    service.start(capture_audio=False)
    service.input_transmission_started("srs-ptt-1", 0)
    service.accept_transcript_segment(_segment("Добрый день", "item-a", 100, 320))
    service.accept_transcript_segment(
        _segment("Разрешите взлёт", "item-b", 700, 980)
    )
    service.input_transmission_completed("srs-ptt-1", 1_400)

    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    assert len(provider.requests) == 1
    assert provider.requests[0].interaction.text == "Добрый день Разрешите взлёт"
    assert len(endpoint.transmissions) == 1
    service.stop()
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode("utf-8").splitlines()
        ]
        summary = json.loads(archive.read("live-golden-summary.json"))
    assert [
        event["event"]
        for event in events
        if event["event"]
        in {
            "live_golden_ptt_started",
            "live_golden_ptt_completed",
            "live_golden_transcript_segment_correlated",
            "live_golden_utterance_finalized",
        }
    ] == [
        "live_golden_ptt_started",
        "live_golden_transcript_segment_correlated",
        "live_golden_transcript_segment_correlated",
        "live_golden_ptt_completed",
        "live_golden_utterance_finalized",
    ]
    assert summary["runs"][0]["cases"][0]["input"]["final_transcript"] == (
        "Добрый день Разрешите взлёт"
    )
    assert [
        event["merge_decision"]
        for event in events
        if event["event"] == "live_golden_transcript_segment_correlated"
    ] == ["INITIAL", "INDEPENDENT_APPEND"]


def test_field_cumulative_hypotheses_dispatch_only_complete_utterance_once(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    service, endpoint, recorder, provider = _service(tmp_path, monkeypatch)
    service.start(capture_audio=False)
    service.input_transmission_started("srs-ptt-1", 0)
    service.accept_transcript_segment(
        _segment("добрый день", "item-a", 1_700, 2_300)
    )
    service.accept_transcript_segment(
        _segment("добрый день разрешите", "item-b", 960, 1_360)
    )
    service.accept_transcript_segment(
        _segment("добрый день разрешите взлет", "item-c", 0, 20)
    )
    service.input_transmission_completed("srs-ptt-1", 4_080)

    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    assert len(provider.requests) == 1
    assert provider.requests[0].interaction.text == "добрый день разрешите взлет"
    assert len(endpoint.transmissions) == 1
    service.stop()
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode("utf-8").splitlines()
        ]
        summary = json.loads(archive.read("live-golden-summary.json"))
    assert [
        event["merge_decision"]
        for event in events
        if event["event"] == "live_golden_transcript_segment_correlated"
    ] == ["INITIAL", "CUMULATIVE_EXTENSION", "CUMULATIVE_EXTENSION"]
    assert summary["runs"][0]["cases"][0]["input"]["final_transcript"] == (
        "добрый день разрешите взлет"
    )


def test_exact_suffix_prefix_overlap_is_merged_without_fuzzy_rewriting() -> None:
    emitted: list[tuple[object, ...]] = []
    coordinator = LiveGoldenPttCoordinator(
        lambda *values: emitted.append(values), settle_seconds=0.01
    )
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.accept_segment(
        _segment("добрый день разрешите", "item-1", 10, 20)
    )
    coordinator.accept_segment(_segment("разрешите взлет", "item-2", 30, 40))
    coordinator.transmission_completed("ptt-1", 100)

    _wait_for_emissions(emitted, 1)
    assert emitted[0][1] == "добрый день разрешите взлет"


def test_same_provider_identity_is_deduplicated_once() -> None:
    emitted: list[tuple[object, ...]] = []
    coordinator = LiveGoldenPttCoordinator(
        lambda *values: emitted.append(values), settle_seconds=0.01
    )
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    segment = _segment("добрый день", "same-item", 10, 20)
    coordinator.accept_segment(segment)
    coordinator.accept_segment(segment)
    coordinator.transmission_completed("ptt-1", 100)

    _wait_for_emissions(emitted, 1)
    assert emitted[0][1] == "добрый день"
    assert emitted[0][3] == 1


def test_legitimate_repetition_inside_provider_text_is_preserved_exactly() -> None:
    emitted: list[tuple[object, ...]] = []
    coordinator = LiveGoldenPttCoordinator(
        lambda *values: emitted.append(values), settle_seconds=0.01
    )
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.accept_segment(_segment("очень очень", "item-1", 10, 20))
    coordinator.accept_segment(_segment("важно", "item-2", 30, 40))
    coordinator.transmission_completed("ptt-1", 100)

    _wait_for_emissions(emitted, 1)
    assert emitted[0][1] == "очень очень важно"


def test_three_independent_fragments_remain_in_arrival_order() -> None:
    emitted: list[tuple[object, ...]] = []
    coordinator = LiveGoldenPttCoordinator(
        lambda *values: emitted.append(values), settle_seconds=0.01
    )
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.accept_segment(_segment("tower", "item-1", 10, 20))
    coordinator.accept_segment(_segment("viper two one", "item-2", 30, 40))
    coordinator.accept_segment(_segment("request takeoff", "item-3", 50, 60))
    coordinator.transmission_completed("ptt-1", 100)

    _wait_for_emissions(emitted, 1)
    assert emitted[0][1] == "tower viper two one request takeoff"


def test_pre_boundary_final_segment_needs_no_later_provider_speech_stop() -> None:
    emitted: list[tuple[object, ...]] = []

    def emit(*values: object) -> None:
        emitted.append(values)

    coordinator = LiveGoldenPttCoordinator(emit, settle_seconds=0.01)
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.accept_segment(_segment("Полная фраза", "item-1", 100, 400))
    coordinator.transmission_completed("ptt-1", 800)

    _wait_for_emissions(emitted, 1)
    assert emitted[0][1] == "Полная фраза"


def test_delayed_post_boundary_transcript_stays_with_same_physical_ptt() -> None:
    emitted: list[tuple[object, ...]] = []

    def emit(*values: object) -> None:
        emitted.append(values)

    coordinator = LiveGoldenPttCoordinator(emit, settle_seconds=0.03)
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.transmission_completed("ptt-1", 900)
    time.sleep(0.01)
    coordinator.provider_activity(500)
    coordinator.accept_segment(_segment("Задержанный сегмент", "item-1", 300, 600))

    _wait_for_emissions(emitted, 1)
    assert emitted[0][0:2] == ("ptt-1", "Задержанный сегмент")


def test_two_ptts_do_not_cross_contaminate_and_drop_stale_segment() -> None:
    emitted: list[tuple[object, ...]] = []

    def emit(*values: object) -> None:
        emitted.append(values)

    coordinator = LiveGoldenPttCoordinator(emit, settle_seconds=0.01)
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.accept_segment(_segment("A", "a", 10, 20))
    coordinator.accept_segment(_segment("A B", "b", 0, 20))
    stale = _segment("STALE", "stale", 50, 60)
    coordinator.transmission_completed("ptt-1", 100)
    _wait_for_emissions(emitted, 1)

    coordinator.arm_next()
    coordinator.transmission_started("ptt-2", 200)
    coordinator.accept_segment(stale)
    coordinator.accept_segment(_segment("C", "c", 10, 20))
    coordinator.accept_segment(_segment("C D", "d", 0, 20))
    coordinator.transmission_completed("ptt-2", 300)
    _wait_for_emissions(emitted, 2)

    assert [value[1] for value in emitted] == ["A B", "C D"]


def test_non_monotonic_provider_position_does_not_override_local_ptt_time() -> None:
    emitted: list[tuple[object, ...]] = []

    def emit(*values: object) -> None:
        emitted.append(values)

    coordinator = LiveGoldenPttCoordinator(emit, settle_seconds=0.01)
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-2", 200)
    coordinator.accept_segment(_segment("CURRENT", "current", 0, 20))
    coordinator.transmission_completed("ptt-2", 300)
    _wait_for_emissions(emitted, 1)

    assert emitted[0][1] == "CURRENT"


def test_speechkit_native_final_bypasses_realtime_ptt_settle_only_for_native_path(
    monkeypatch,
) -> None:  # noqa: ANN001
    service = LiveGoldenConversationService(ptt_settle_seconds=60.0)
    accepted: list[tuple[object, ...]] = []

    def accept(*args: object) -> bool:
        accepted.append(args)
        return True

    monkeypatch.setattr(service, "accept_transcript", accept)
    service.accept_native_finalized_utterance(
        FinalizedUserUtterance(
            transmission_id="srs-ptt-1",
            transcript="так он недоступен",
            provider_id="speechkit_v3",
            provider_session_id="provider-session",
            provider_final_index=2,
            event_id="final-2",
            provider_item_id="item-2",
            finalized_at=123.0,
        )
    )

    assert accepted == [
        (
            "так он недоступен",
            "srs-ptt-1",
            "final-2",
            "item-2",
            123.0,
        )
    ]
    assert service._ptt_coordinator._pending == {}


def test_delayed_cumulative_extension_before_settle_replaces_early_hypothesis() -> None:
    emitted: list[tuple[object, ...]] = []
    coordinator = LiveGoldenPttCoordinator(
        lambda *values: emitted.append(values), settle_seconds=0.04
    )
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.accept_segment(_segment("добрый день", "item-1", 100, 300))
    coordinator.transmission_completed("ptt-1", 900)
    time.sleep(0.01)
    coordinator.accept_segment(
        _segment("добрый день разрешите взлет", "item-2", 0, 20)
    )

    _wait_for_emissions(emitted, 1)
    assert emitted[0][1] == "добрый день разрешите взлет"


def test_pending_ptt_cancel_prevents_late_semantic_dispatch() -> None:
    emitted: list[tuple[object, ...]] = []

    def emit(*values: object) -> None:
        emitted.append(values)

    coordinator = LiveGoldenPttCoordinator(emit, settle_seconds=0.02)
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.accept_segment(_segment("Не отправлять", "item-1", 10, 20))
    coordinator.transmission_completed("ptt-1", 100)
    coordinator.cancel()
    time.sleep(0.05)

    assert emitted == []


def test_coordinator_preserves_bad_raw_stt_without_rewriting() -> None:
    emitted: list[tuple[object, ...]] = []

    def emit(*values: object) -> None:
        emitted.append(values)

    coordinator = LiveGoldenPttCoordinator(emit, settle_seconds=0.01)
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.accept_segment(_segment("выключить", "item-1", 10, 20))
    coordinator.accept_segment(
        _segment("выключить разрешите", "item-2", 30, 40)
    )
    coordinator.accept_segment(
        _segment("выключить разрешите все", "item-3", 0, 20)
    )
    coordinator.transmission_completed("ptt-1", 100)

    _wait_for_emissions(emitted, 1)
    assert emitted[0][1] == "выключить разрешите все"


def test_distinct_provider_events_preserve_genuine_repeated_phrase() -> None:
    emitted: list[tuple[object, ...]] = []
    coordinator = LiveGoldenPttCoordinator(
        lambda *values: emitted.append(values), settle_seconds=0.01
    )
    coordinator.reset_and_arm()
    coordinator.transmission_started("ptt-1", 0)
    coordinator.accept_segment(_segment("да", "item-1", 10, 20))
    coordinator.accept_segment(_segment("да", "item-2", 30, 40))
    coordinator.transmission_completed("ptt-1", 100)

    _wait_for_emissions(emitted, 1)
    assert emitted[0][1] == "да да"


def test_real_transcript_runs_one_qwen_local_protected_composition_and_one_radio_tx(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    service, endpoint, recorder, _provider = _service(tmp_path, monkeypatch)
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
    service, endpoint, recorder, _provider = _service(tmp_path, monkeypatch)
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
    service, endpoint, recorder, _provider = _service(tmp_path, monkeypatch)
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
    service, endpoint, recorder, _provider = _service(tmp_path, monkeypatch, gate=gate)
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
