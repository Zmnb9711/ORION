from __future__ import annotations

import json
import threading
import time
import zipfile
from pathlib import Path

import orion.live_golden_conversation as live_module
import pytest

from orion.aircraft_identity_query import (
    AircraftIdentityFormulationService,
    AircraftIdentityQueryService,
    AircraftIdentityRealtimeRuntime,
)
from orion.atc_status_query import PersistentAtcSessionCoordinator
from orion.communication_contracts import CommunicationDomain
from orion.launcher_cloud_voice_sections import (
    CloudVoiceConfig,
    LauncherCloudVoiceSectionsMixin,
)
from orion.live_golden_conversation import (
    AIRCRAFT_IDENTITY_CASE,
    AIRCRAFT_IDENTITY_FIELD_CORPUS,
    ATC_STATUS_CASE,
    LIVE_GOLDEN_CORPUS,
    PURE_TAKEOFF_FIRST_CORPUS,
    InformationalPresentationBackend,
    LiveGoldenAcousticReview,
    LiveGoldenConversationService,
    LiveGoldenPttCoordinator,
    LiveGoldenRuntimeContext,
    LiveGoldenState,
)
from orion.mixed_conversation import mixed_decomposition_tool_definition
from orion.live_telemetry_store import LiveTelemetryStore
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.planner_contracts import (
    PlannerFinalResponseEvent,
    PlannerToolCallsEvent,
    PlannerToolRequest,
    PlannerUsage,
)
from orion.interaction_contracts import PresentationMode, SemanticResponse
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.radio_streaming import StreamingPcmEvent, StreamingPcmState
from orion.realtime_audio_transport import (
    FinalizedUserUtterance,
    RealtimeTranscriptSegment,
)
from orion.realtime_live_core import RealtimeLiveCoordinator, RealtimeLiveStartRequest
from orion.realtime_provider import RealtimeLiveStatus
from orion.srs_radio_adapter import SrsAdapterRuntime
from orion.srs_radio_transport import SrsState
from orion.tool_gateway_contracts import ToolArguments
from orion.yandex_speechkit_streaming_tts import SpeechKitTtsOutputMode
from orion.yandex_realtime_informational_presenter import (
    YandexRealtimeInformationalPresenter,
    YandexRealtimeTextConfig,
)
from orion.yandex_srs_live_core import YandexSrsStartRequest, YandexSrsStatus
from orion.world_model import WorldModelFacade


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


class _FormulationRun:
    def __init__(self, request, recommendation: str) -> None:  # noqa: ANN001
        self.request = request
        self.recommendation = recommendation

    def next_event(self, **_kwargs):  # noqa: ANN003, ANN202
        return PlannerFinalResponseEvent(
            event_id="aircraft-formulation-event",
            response=SemanticResponse(
                interaction_id=self.request.interaction.interaction_id,
                presentation_mode=PresentationMode.NATURALIZE,
                recommendation=self.recommendation,
            ),
            usage=PlannerUsage(
                model_identifier="qwen3.6-35b-a3b",
                provider_request_ids=("qwen-aircraft-response-1",),
                provider_attempts=1,
                provider_latency_ms=9.0,
            ),
        )

    def continue_with_tool_results(self, _results) -> None:  # noqa: ANN001
        raise AssertionError("Aircraft formulation has no tool round")

    def cancel(self) -> None:
        return None


class _Provider:
    provider_id = "fake.qwen"

    def __init__(
        self,
        *,
        gate: threading.Event | None = None,
        aircraft_recommendation: str = "Вы сейчас находитесь в {{aircraft_identity}}.",
    ) -> None:
        self.gate = gate
        self.aircraft_recommendation = aircraft_recommendation
        self.requests = []

    def start(self, request):  # noqa: ANN001, ANN201
        self.requests.append(request)
        if any("{{aircraft_identity}}" in item for item in request.core_instructions):
            return _FormulationRun(request, self.aircraft_recommendation)
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
        assert any(
            marker in case.finalized_text
            for marker in (
                "Viper 2-1",
                "Добрый день",
                "Диагностический статус ATC",
                "По данным DCS",
                "F/A-18C Hornet",
            )
        )
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


class _StreamingSuccess:
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
            pcm=b"\x01\x00" * 48_000,
            sample_rate_hz=48_000,
            channels=1,
            sample_width_bytes=2,
            chunk_index=0,
        )
        yield StreamingPcmEvent(
            response_id=response_id,
            pcm=b"",
            sample_rate_hz=48_000,
            channels=1,
            sample_width_bytes=2,
            chunk_index=1,
            end_of_stream=True,
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

    def transmit_streaming_audio(
        self,
        response_id: str,
        stream,
        timeout_s: float,
        **fields,
    ) -> dict[str, float | int]:  # noqa: ANN001, ANN003
        pcm = bytearray()
        while True:
            read = stream.read(8_820, timeout_s=timeout_s)
            pcm.extend(read.data)
            if read.state is StreamingPcmState.END_OF_STREAM and not read.data:
                break
            if read.state in {StreamingPcmState.FAILED, StreamingPcmState.CANCELLED}:
                raise RuntimeError(read.error or read.state.value)
        self.transmissions.append(
            {
                "response_id": response_id,
                "pcm": bytes(pcm),
                "timeout_s": timeout_s,
                **fields,
            }
        )
        return {
            "queue_to_first_tx_ms": 2.0,
            "queue_to_complete_ms": 102.0,
            "frame_count": 5,
            "duration_ms": 100.0,
            "underrun_count": 0,
            "underrun_silence_inserted_ms": 0.0,
        }


class _C3Transport:
    def __init__(
        self,
        _config: YandexRealtimeTextConfig,
        *,
        conformant: bool = True,
    ) -> None:
        import asyncio

        self.events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.sent: list[dict[str, object]] = []
        self.operation = "info"
        self.response_index = 0
        self.closed = False
        self.conformant = conformant

    async def connect(self) -> None:
        return None

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)
        kind = payload.get("type")
        if kind == "session.update":
            self.events.put_nowait(
                {"type": "session.updated", "session": {"id": "c3-session"}}
            )
            return
        if kind == "conversation.item.create":
            self.operation = (
                "semantic"
                if "-semantic-" in str(payload.get("event_id") or "")
                else "info"
            )
            return
        if kind != "response.create":
            return
        self.response_index += 1
        response_id = f"c3-response-{self.response_index}"
        text = (
            (
                '{"conformant":true,"reason":"only Core-confirmed facts"}'
                if self.conformant
                else '{"conformant":false,"reason":"unsupported assertion"}'
            )
            if self.operation == "semantic"
            else "Вы в {{aircraft_identity}}, текущий курс 137 градусов."
        )
        for event in (
            {"type": "response.created", "response": {"id": response_id}},
            {
                "type": "response.output_text.delta",
                "response_id": response_id,
                "delta": text,
            },
            {
                "type": "response.output_text.done",
                "response_id": response_id,
                "text": text,
            },
            {
                "type": "response.done",
                "response": {"id": response_id, "status": "completed"},
            },
        ):
            self.events.put_nowait(event)

    async def receive_json(self) -> dict[str, object]:
        return await self.events.get()

    async def close(self) -> None:
        self.closed = True


def _wait_for(service: LiveGoldenConversationService, state: LiveGoldenState) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if service.status().state is state:
            return
        time.sleep(0.01)
    raise AssertionError(f"Live Golden did not reach {state}: {service.status()}")


def _c3_runtime(
    query: AircraftIdentityQueryService,
    transports: list[_C3Transport],
    *,
    conformant: bool = True,
) -> AircraftIdentityRealtimeRuntime:
    def presenter_factory(config, diagnostics):  # noqa: ANN001, ANN202
        def transport_factory(inner: YandexRealtimeTextConfig) -> _C3Transport:
            transport = _C3Transport(inner, conformant=conformant)
            transports.append(transport)
            return transport

        return YandexRealtimeInformationalPresenter(
            config,
            diagnostics=diagnostics,
            transport_factory=transport_factory,
        )

    return AircraftIdentityRealtimeRuntime(
        query=query,
        presenter_factory=presenter_factory,
    )


def _service(
    tmp_path: Path,
    monkeypatch,
    *,
    gate: threading.Event | None = None,
    tts_output_mode: SpeechKitTtsOutputMode = SpeechKitTtsOutputMode.REST_BUFFERED,
    streaming_speechkit_factory=None,  # noqa: ANN001
    corpus=LIVE_GOLDEN_CORPUS,  # noqa: ANN001
    atc_sessions=None,  # noqa: ANN001
    aircraft_identity_service=None,  # noqa: ANN001
    informational_runtime=None,  # noqa: ANN001
    aircraft_recommendation: str = "Вы сейчас находитесь в {{aircraft_identity}}.",
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
    provider = _Provider(
        gate=gate,
        aircraft_recommendation=aircraft_recommendation,
    )
    runner = live_module.LiveGoldenCaseRunner(
        provider_factory=lambda _config: provider,
        speechkit_factory=_SpeechKit,
        streaming_speechkit_factory=(
            streaming_speechkit_factory or live_module.SpeechKitStreamingTtsClient
        ),
        aircraft_identity_service=aircraft_identity_service,
    )
    service = LiveGoldenConversationService(
        runner=runner,
        ptt_settle_seconds=0.01,
        corpus=corpus,
        atc_sessions=atc_sessions,
    )
    endpoint = _Endpoint()
    service.attach(
        LiveGoldenRuntimeContext(
            api_key="memory-only-secret",
            folder_id="folder-id",
            endpoint=endpoint,
            main_session_id="yandex-main-session",
            tts_output_mode=tts_output_mode,
            informational_runtime=(
                informational_runtime or AircraftIdentityRealtimeRuntime()
            ),
        )
    )
    return service, endpoint, recorder, provider


def test_live_dcs_aircraft_identity_field_case_uses_core_truth_and_qwen_wording(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    observed_at = live_module.datetime.now(live_module.UTC)
    telemetry = LiveTelemetryStore()
    telemetry.set(
        TelemetryEnvelope(
            sequence=1,
            state=AircraftState(
                aircraft_type="FA-18C_hornet",
                position=Position(latitude=42.1, longitude=41.2, altitude_m=1000),
                heading_deg=137,
                true_airspeed_mps=145,
            ),
        ),
        received_at=observed_at,
    )
    identity_service = AircraftIdentityFormulationService(
        query=AircraftIdentityQueryService(
            WorldModelFacade(telemetry=telemetry, clock=lambda: observed_at)
        )
    )
    service, endpoint, recorder, provider = _service(
        tmp_path,
        monkeypatch,
        corpus=AIRCRAFT_IDENTITY_FIELD_CORPUS,
        aircraft_identity_service=identity_service,
        tts_output_mode=SpeechKitTtsOutputMode.STREAMING_V3,
        streaming_speechkit_factory=_StreamingSuccess,
    )
    status = service.start(capture_audio=False)
    assert status.total_cases == 1
    assert status.next_prompt == AIRCRAFT_IDENTITY_CASE.prompt

    assert service.accept_transcript(
        AIRCRAFT_IDENTITY_CASE.prompt,
        "aircraft-ptt",
        "aircraft-event",
        "aircraft-item",
        time.monotonic(),
    )
    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    assert len(provider.requests) == 1
    assert provider.requests[0].allowed_capabilities == ()
    assert provider.requests[0].available_tools == ()
    assert len(endpoint.transmissions) == 1
    assert endpoint.transmissions[0]["source_domain"] is CommunicationDomain.GENERAL
    assert endpoint.transmissions[0]["entity_id"] == (
        "orion.assistant.aircraft_information"
    )

    final = service.review(LiveGoldenAcousticReview.CLEAR)
    assert final.state is LiveGoldenState.COMPLETE
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        summary = json.loads(archive.read("live-golden-summary.json"))
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode().splitlines()
        ]
        combined = b"".join(archive.read(name) for name in archive.namelist())

    record = summary["runs"][0]["cases"][0]
    assert record["semantic_route"] == {
        "recognizer_evaluated": True,
        "contract_matched": True,
        "pure": True,
        "route_selected": "deterministic_known_contract",
        "reason_code": "pure_aircraft_identity_query",
        "contract": "aircraft_identity_query",
        "qwen_required": False,
        "qwen_formulation_required": True,
        "qwen_call_count": 1,
        "informational_backend": "CURRENT_QWEN",
        "policy_version": "model-c.known-contract-policy.v1",
    }
    assert record["qwen"]["semantic_interpretation_required"] is False
    assert record["qwen"]["natural_language_formulation_required"] is True
    assert record["qwen"]["call_count"] == 1
    assert record["qwen"]["fact_authority"] is False
    assert record["qwen"]["provider"] == "fake.qwen"
    assert record["qwen"]["provider_response_ids"] == [
        "qwen-aircraft-response-1"
    ]
    assert record["aircraft_identity"]["truth_origin"] == "LIVE_DCS_TRUTH"
    assert record["aircraft_identity"]["raw_dcs_aircraft_id"] == "FA-18C_hornet"
    assert record["aircraft_identity"]["display_name"] == "F/A-18C Hornet"
    assert record["aircraft_identity"]["source"] == "dcs_export"
    assert record["aircraft_identity"]["authority"] == "authoritative"
    assert record["aircraft_identity"]["fact_status"] == "known"
    assert record["aircraft_identity"]["stable_dcs_session_epoch"] == "NOT AVAILABLE"
    assert record["final_composed_text"] == "Вы сейчас находитесь в F/A-18C Hornet."
    assert record["communication_profile"] == "NOT_APPLICABLE_INFORMATIONAL"
    assert record["radio"]["entity_id"] == "orion.assistant.aircraft_information"
    assert record["speechkit"]["output_mode"] == "speechkit_v3_streaming"
    assert record["speechkit"]["streaming_requested"] is True
    assert record["speechkit"]["streaming_rest_fallback"] is False
    assert record["internal_result"] == "PASS"
    assert any(
        event["event"] == "live_golden_aircraft_identity_resolved"
        and event["fact_origin"] == "LIVE_DCS_TRUTH"
        and event["aircraft_type"] == "FA-18C_hornet"
        and event["aircraft_display_name"] == "F/A-18C Hornet"
        and event["source"] == "dcs_export"
        and event["authority"] == "authoritative"
        and event["context_fresh"] is True
        and event["qwen_call_count"] == 1
        and event["qwen_fact_authority"] is False
        and event["formulation_origin"] == "qwen_validated_placeholder"
        for event in events
    )
    assert b"memory-only-secret" not in combined


def test_c3_realtime_candidate_integrates_full_route_reuses_session_and_calls_no_qwen(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    observed_at = live_module.datetime.now(live_module.UTC)
    telemetry = LiveTelemetryStore()
    telemetry.set(
        TelemetryEnvelope(
            sequence=1,
            state=AircraftState(
                aircraft_type="FA-18C_hornet",
                position=Position(latitude=42.1, longitude=41.2, altitude_m=1000),
                heading_deg=137,
                true_airspeed_mps=145,
            ),
        ),
        received_at=observed_at,
    )
    query = AircraftIdentityQueryService(
        WorldModelFacade(telemetry=telemetry, clock=lambda: observed_at)
    )
    transports: list[_C3Transport] = []
    runtime = _c3_runtime(query, transports)
    service, endpoint, recorder, provider = _service(
        tmp_path,
        monkeypatch,
        corpus=AIRCRAFT_IDENTITY_FIELD_CORPUS,
        informational_runtime=runtime,
    )

    for index in range(2):
        status = service.start(
            capture_audio=False,
            informational_backend=(
                InformationalPresentationBackend.REALTIME_D75_CANDIDATE
            ),
        )
        assert status.informational_backend is (
            InformationalPresentationBackend.REALTIME_D75_CANDIDATE
        )
        assert service.accept_transcript(
            AIRCRAFT_IDENTITY_CASE.prompt,
            f"aircraft-ptt-{index}",
            f"aircraft-event-{index}",
            f"aircraft-item-{index}",
            time.monotonic(),
        )
        _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
        service.review(LiveGoldenAcousticReview.CLEAR)

    assert provider.requests == []
    assert len(transports) == 1
    assert len(endpoint.transmissions) == 2
    service.detach("yandex-main-session")
    assert transports[0].closed is True
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        summary = json.loads(archive.read("live-golden-summary.json"))
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode().splitlines()
        ]
        combined = b"".join(archive.read(name) for name in archive.namelist())

    cases = [run["cases"][0] for run in summary["runs"]]
    assert all(
        case["semantic_route"]["informational_backend"]
        == "REALTIME_D75_CANDIDATE"
        for case in cases
    )
    assert all(case["qwen"]["call_count"] == 0 for case in cases)
    assert all(
        case["final_composed_text"]
        == "Вы в F/A-18C Hornet, текущий курс 137 градусов."
        for case in cases
    )
    assert cases[0]["informational_presentation"]["session_reused"] is False
    assert cases[1]["informational_presentation"]["session_reused"] is True
    assert all(case["internal_result"] == "PASS" for case in cases)
    assert any(event["event"] == "formulation_session_ready" for event in events)
    assert sum(
        event["event"] == "informational_backend_selected" for event in events
    ) == 2
    assert sum(
        event["event"] == "semantic_validation_completed" for event in events
    ) == 2
    assert b"memory-only-secret" not in combined


def test_c3_semantic_rejection_fails_before_tts_radio_and_qwen(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    observed_at = live_module.datetime.now(live_module.UTC)
    telemetry = LiveTelemetryStore()
    telemetry.set(
        TelemetryEnvelope(
            sequence=1,
            state=AircraftState(
                aircraft_type="FA-18C_hornet",
                position=Position(latitude=42.1, longitude=41.2, altitude_m=1000),
                heading_deg=137,
                true_airspeed_mps=145,
            ),
        ),
        received_at=observed_at,
    )
    query = AircraftIdentityQueryService(
        WorldModelFacade(telemetry=telemetry, clock=lambda: observed_at)
    )
    transports: list[_C3Transport] = []
    runtime = _c3_runtime(query, transports, conformant=False)
    service, endpoint, recorder, provider = _service(
        tmp_path,
        monkeypatch,
        corpus=AIRCRAFT_IDENTITY_FIELD_CORPUS,
        informational_runtime=runtime,
    )
    service.start(
        capture_audio=False,
        informational_backend=InformationalPresentationBackend.REALTIME_D75_CANDIDATE,
    )
    assert service.accept_transcript(
        AIRCRAFT_IDENTITY_CASE.prompt,
        "aircraft-ptt",
        "aircraft-event",
        "aircraft-item",
        time.monotonic(),
    )
    _wait_for(service, LiveGoldenState.FAIL)
    assert endpoint.transmissions == []
    assert provider.requests == []
    service.detach("yandex-main-session")
    recorder.stop_and_export()


def test_c3_unavailable_session_rejects_start_without_qwen_tts_or_radio(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    class _UnavailableTransport(_C3Transport):
        async def connect(self) -> None:
            raise OSError("bounded unavailable fixture")

    def presenter_factory(config, diagnostics):  # noqa: ANN001, ANN202
        return YandexRealtimeInformationalPresenter(
            config,
            diagnostics=diagnostics,
            transport_factory=lambda inner: _UnavailableTransport(inner),
        )

    runtime = AircraftIdentityRealtimeRuntime(presenter_factory=presenter_factory)
    service, endpoint, recorder, provider = _service(
        tmp_path,
        monkeypatch,
        corpus=AIRCRAFT_IDENTITY_FIELD_CORPUS,
        informational_runtime=runtime,
    )

    with pytest.raises(ValueError, match="candidate is not ready: session_unavailable"):
        service.start(
            capture_audio=False,
            informational_backend=(
                InformationalPresentationBackend.REALTIME_D75_CANDIDATE
            ),
        )

    assert service.status().state is LiveGoldenState.OFF
    assert provider.requests == []
    assert endpoint.transmissions == []
    service.detach("yandex-main-session")
    recorder.stop_and_export()


def test_c3_selector_does_not_take_over_protected_takeoff_route(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    runtime = AircraftIdentityRealtimeRuntime()
    service, endpoint, recorder, provider = _service(
        tmp_path,
        monkeypatch,
        corpus=(PURE_TAKEOFF_FIRST_CORPUS[0],),
        informational_runtime=runtime,
    )
    service.start(
        capture_audio=False,
        informational_backend=InformationalPresentationBackend.REALTIME_D75_CANDIDATE,
    )
    assert runtime.ready is False
    assert service.accept_transcript(
        "Разрешите взлёт.",
        "takeoff-ptt",
        "takeoff-event",
        "takeoff-item",
        time.monotonic(),
    )
    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    assert provider.requests == []
    assert len(endpoint.transmissions) == 1
    service.stop()
    service.detach("yandex-main-session")
    recorder.stop_and_export()


def test_aircraft_identity_qwen_override_fails_before_tts_or_radio(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    observed_at = live_module.datetime.now(live_module.UTC)
    telemetry = LiveTelemetryStore()
    telemetry.set(
        TelemetryEnvelope(
            sequence=1,
            state=AircraftState(
                aircraft_type="FA-18C_hornet",
                position=Position(latitude=42.1, longitude=41.2, altitude_m=1000),
                heading_deg=137,
                true_airspeed_mps=145,
            ),
        ),
        received_at=observed_at,
    )
    identity_service = AircraftIdentityFormulationService(
        query=AircraftIdentityQueryService(
            WorldModelFacade(telemetry=telemetry, clock=lambda: observed_at)
        )
    )
    service, endpoint, recorder, provider = _service(
        tmp_path,
        monkeypatch,
        corpus=AIRCRAFT_IDENTITY_FIELD_CORPUS,
        aircraft_identity_service=identity_service,
        aircraft_recommendation="Вы сейчас находитесь в F-16C Viper.",
    )
    service.start(capture_audio=False)
    assert service.accept_transcript(
        AIRCRAFT_IDENTITY_CASE.prompt,
        "aircraft-ptt",
        "aircraft-event",
        "aircraft-item",
        time.monotonic(),
    )
    _wait_for(service, LiveGoldenState.FAIL)

    assert len(provider.requests) == 1
    assert endpoint.transmissions == []
    assert service.status().message == "Live Golden failed closed at qwen_formulation"
    recorder.stop_and_export()


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


def test_launcher_to_live_golden_streaming_provider_propagates_end_to_end(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    class Bridge:
        provider_id = "yandex"
        transport_id = "srs"

        def __init__(self) -> None:
            self.request: YandexSrsStartRequest | None = None
            self.runtime_status: YandexSrsStatus | None = None
            self.state = "stopped"

        def start_live(self, payload):  # noqa: ANN001, ANN202
            srs = payload.pop("srs")
            self.request = YandexSrsStartRequest.model_validate({**payload, **srs})
            self.runtime_status = YandexSrsStatus(
                state="streaming",
                radio_stt_provider=self.request.radio_stt_provider,
                tts_output_mode=self.request.tts_output_mode,
            )
            self.state = "streaming"
            return self.live_status()

        def live_status(self) -> RealtimeLiveStatus:
            return RealtimeLiveStatus(
                provider="yandex",
                transport="srs",
                state=self.state,
            )

        def stop_live(self) -> RealtimeLiveStatus:
            self.state = "stopped"
            return self.live_status()

    selected = CloudVoiceConfig(
        cloud_provider="yandex",
        voice_transport="srs",
        yandex_folder_id="folder",
        radio_stt_provider="speechkit_v3",
        tts_output_mode="speechkit_v3_streaming",
    )
    launcher_payload = LauncherCloudVoiceSectionsMixin._realtime_start_payload(
        selected,
        "unused-qwen",
        "memory-only-yandex",
        "memory-only-eam",
    )
    core_request = RealtimeLiveStartRequest.model_validate(launcher_payload)
    assert core_request.model_dump()["tts_output_mode"] == "speechkit_v3_streaming"

    bridge = Bridge()
    RealtimeLiveCoordinator([bridge]).start(core_request)
    assert bridge.request is not None
    assert bridge.runtime_status is not None
    assert bridge.request.tts_output_mode is SpeechKitTtsOutputMode.STREAMING_V3
    assert (
        bridge.runtime_status.tts_output_mode
        is SpeechKitTtsOutputMode.STREAMING_V3
    )

    streaming_factories: list[object] = []

    def streaming_factory() -> _StreamingFailureBeforeTx:
        streaming_factories.append(object())
        return _StreamingFailureBeforeTx()

    service, endpoint, recorder, _provider = _service(
        tmp_path,
        monkeypatch,
        tts_output_mode=bridge.request.tts_output_mode,
        streaming_speechkit_factory=streaming_factory,
    )
    service.start(capture_audio=False)
    service.input_transmission_started("srs-propagation-ptt", 0)
    service.accept_transcript_segment(
        _segment("Добрый день Разрешите взлёт", "propagation-item", 0, 900)
    )
    service.input_transmission_completed("srs-propagation-ptt", 1_000)
    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)

    assert len(streaming_factories) == 1
    assert len(endpoint.transmissions) == 1
    service.stop()
    recorder.stop_and_export()


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
    assert endpoint.transmissions[0]["entity_id"] == "orion.atc.airport_tower"

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
    assert case["speechkit"]["output_mode"] == "speechkit_rest"
    assert case["speechkit"]["streaming_requested"] is False
    assert case["speechkit"]["streaming_rest_fallback"] is False
    assert case["acoustic_review"] == "clear"
    assert "live-golden-audio/mixed-ru-1.wav" in names
    assert "orion_build_sha=9f38d449" in session
    assert "orion_build_branch=dev/adr004-post-389" in session
    assert b"memory-only-secret" not in combined


def test_pure_takeoff_routes_before_qwen_once_through_existing_atc_phraseology_and_radio(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    service, endpoint, recorder, provider = _service(
        tmp_path,
        monkeypatch,
        corpus=PURE_TAKEOFF_FIRST_CORPUS,
    )
    status = service.start(capture_audio=False)
    assert status.next_prompt == "Разрешите взлёт."

    for _ in range(2):
        service.accept_transcript(
            "Разрешите взлёт.",
            "takeoff-ptt-1",
            "takeoff-event-1",
            "takeoff-item-1",
            time.monotonic(),
        )
    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    assert provider.requests == []
    assert len(endpoint.transmissions) == 1

    service.stop()
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        summary = json.loads(archive.read("live-golden-summary.json"))
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode().splitlines()
        ]
    record = summary["runs"][0]["cases"][0]
    assert record["semantic_route"] == {
        "recognizer_evaluated": True,
        "contract_matched": True,
        "pure": True,
        "route_selected": "deterministic_known_contract",
        "reason_code": "pure_takeoff_clearance_request",
        "contract": "takeoff_clearance_request",
        "qwen_required": False,
        "qwen_call_count": 0,
        "policy_version": "model-c.known-contract-policy.v1",
    }
    assert record["qwen"]["call_count"] == 0
    assert record["qwen"]["provider_response_ids"] == []
    assert record["atc"]["decision"]["status"] == "granted"
    assert record["semantic_result"] == {
        "atc_result_count": 1,
        "osu_count": 1,
        "phraseology_count": 1,
        "presentation_response_count": 1,
    }
    assert record["phraseology_entry_id"] == "atc-takeoff-clearance-granted"
    assert record["protected_fragment"] == (
        "Viper 2-1, полоса 07/25, взлёт разрешён."
    )
    assert record["final_composed_text"] == record["protected_fragment"]
    assert record["composition_order"] == ["PROTECTED"]
    assert record["internal_result"] == "PASS"
    assert any(
        event["event"] == "live_golden_core_semantics_completed"
        and event["qwen_call_count"] == 0
        and event["osu_count"] == 1
        and event["phraseology_count"] == 1
        for event in events
    )


def test_takeoff_then_status_use_same_persistent_atc_session_without_qwen(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    atc_sessions = PersistentAtcSessionCoordinator()
    service, endpoint, recorder, provider = _service(
        tmp_path,
        monkeypatch,
        corpus=(PURE_TAKEOFF_FIRST_CORPUS[0], ATC_STATUS_CASE),
        atc_sessions=atc_sessions,
    )
    status = service.start(capture_audio=False)
    assert status.next_prompt == "Разрешите взлёт."

    assert service.accept_transcript(
        "Разрешите взлёт.",
        "takeoff-ptt",
        "takeoff-event",
        "takeoff-item",
        time.monotonic(),
    )
    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    status = service.review(LiveGoldenAcousticReview.CLEAR)
    assert status.next_prompt == ATC_STATUS_CASE.prompt

    assert service.accept_transcript(
        ATC_STATUS_CASE.prompt,
        "status-ptt",
        "status-event",
        "status-item",
        time.monotonic(),
    )
    _wait_for(service, LiveGoldenState.AWAITING_REVIEW)
    assert provider.requests == []
    assert len(endpoint.transmissions) == 2
    assert endpoint.transmissions[0]["entity_id"] == "orion.atc.airport_tower"
    assert endpoint.transmissions[1]["entity_id"] == "orion.atc.airport_tower"

    final = service.review(LiveGoldenAcousticReview.CLEAR)
    assert final.state is LiveGoldenState.COMPLETE
    assert status.run_id is not None
    assert atc_sessions.bound_session_id(
        main_session_id="yandex-main-session",
        run_id=status.run_id,
    ) is None
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        summary = json.loads(archive.read("live-golden-summary.json"))
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode().splitlines()
        ]
    takeoff, status_record = summary["runs"][0]["cases"]
    assert takeoff["atc"]["session_created"] is True
    assert takeoff["atc"]["session_id"] == status_record["atc"]["session_id"]
    assert status_record["semantic_route"]["contract"] == "atc_status_query"
    assert status_record["semantic_route"]["qwen_call_count"] == 0
    assert status_record["qwen"]["call_count"] == 0
    assert status_record["atc"]["authority_scope"] == "flight_traffic"
    assert status_record["atc"]["controller_agency"] == "airport_tower"
    assert status_record["atc"]["procedural_state"] == "takeoff_cleared"
    assert status_record["atc"]["runtime_revision_before"] == (
        status_record["atc"]["runtime_revision_after"]
    )
    assert status_record["atc"]["atc_truth_unchanged"] is True
    assert status_record["communication_profile"] == "NOT_APPLICABLE_DIAGNOSTIC"
    assert status_record["phraseology_entry_id"] is None
    assert status_record["internal_result"] == "PASS"
    assert any(
        event["event"] == "live_golden_atc_status_resolved"
        and event["atc_session_id"] == takeoff["atc"]["session_id"]
        and event["qwen_call_count"] == 0
        and event["atc_truth_unchanged"] is True
        for event in events
    )


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
    service, endpoint, recorder, provider = _service(tmp_path, monkeypatch)
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
    assert len(provider.requests) == 7
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
