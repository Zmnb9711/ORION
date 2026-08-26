from __future__ import annotations

import json
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from orion.interaction_contracts import CapabilityId, InteractionRequest
from orion.launcher_cloud_voice_sections import CloudVoiceConfig, CloudVoiceConfigStore
from orion.live_telemetry_store import LiveTelemetryStore
from orion.mission import MissionSnapshot
from orion.mission_bridge_ingest import MissionBridgeState
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.planner import PlannerCancellationToken, PlannerTaskRunner
from orion.planner_contracts import (
    PlannerErrorCode,
    PlannerExecutionPolicy,
    PlannerFailedEvent,
    PlannerFinalResponseEvent,
    PlannerProviderRequest,
    PlannerToolCallsEvent,
    ProviderRetryPolicy,
)
from orion.tool_gateway import build_tool_gateway
from orion.windows_credentials import MemoryCredentialBackend, VoiceCredential, VoiceCredentialStore
from orion.world_model import WorldModelFacade
from orion.yandex_qwen_planner import (
    AiohttpYandexResponsesTransport,
    QWEN_MODEL_ID,
    QWEN_PROVIDER_ID,
    YandexFailureCategory,
    YandexPlannerConfigurationError,
    YandexPlannerDiagnostics,
    YandexPlannerTransportError,
    YandexQwenPlannerConfig,
    YandexQwenPlannerProvider,
    YandexTransportResponse,
    _provider_tool_name,
    _read_bounded_json,
    _http_failure,
    load_yandex_qwen_planner_config,
)


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
INTERACTION_ID = UUID("12345678-1234-5678-1234-567812345678")


@dataclass
class FakeTransport:
    responses: list[YandexTransportResponse | Exception]
    payloads: list[Mapping[str, Any]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    closed: bool = False

    def create(
        self,
        payload: Mapping[str, Any],
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken,
    ) -> YandexTransportResponse:
        assert deadline.tzinfo is not None
        assert not cancellation.cancelled
        self.payloads.append(payload)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def delete(self, response_id: str) -> None:
        self.deleted.append(response_id)

    def close(self) -> None:
        self.closed = True


@dataclass
class MissionOwner:
    snapshot: MissionSnapshot | None = None

    def get(self) -> MissionSnapshot | None:
        return self.snapshot


@dataclass
class BridgeOwner:
    snapshot: MissionBridgeState = field(default_factory=MissionBridgeState)

    def state(self) -> MissionBridgeState:
        return self.snapshot.model_copy(deep=True)


def config() -> YandexQwenPlannerConfig:
    return YandexQwenPlannerConfig(folder_id="folder-123", api_key="unit-key")


def interaction(*capabilities: str) -> InteractionRequest:
    return InteractionRequest(
        interaction_id=INTERACTION_ID,
        text="Where am I and what is my current heading?",
        allowed_capabilities=tuple(CapabilityId(item) for item in capabilities),
        created_at=NOW,
    )


def gateway():  # type: ignore[no-untyped-def]
    telemetry = LiveTelemetryStore()
    telemetry.set(
        TelemetryEnvelope(
            sequence=1,
            state=AircraftState(
                aircraft_type="FA-18C_hornet",
                callsign="Colt 1-1",
                position=Position(latitude=42.1, longitude=41.2, altitude_m=2100),
                heading_deg=137,
                true_airspeed_mps=145,
            ),
        ),
        received_at=NOW - timedelta(seconds=1),
    )
    world = WorldModelFacade(
        telemetry=telemetry,
        mission=MissionOwner(),
        mission_bridge=BridgeOwner(),
        clock=lambda: NOW,
    )
    return build_tool_gateway(world=world, clock=lambda: NOW, monotonic=lambda: 10.0)


def provider_request(*capabilities: str) -> PlannerProviderRequest:
    allowed = tuple(CapabilityId(item) for item in capabilities)
    definitions = tuple(
        item for item in gateway().definitions() if item.capability in allowed
    )
    return PlannerProviderRequest(
        planner_task_id="planner-test",
        interaction=interaction(*capabilities),
        allowed_capabilities=allowed,
        available_tools=definitions,
        core_instructions=("Use only Core tool results for facts.",),
        deadline=NOW + timedelta(minutes=1),
        retry_policy=ProviderRetryPolicy(max_attempts=2),
    )


def response(response_id: str, output: list[dict[str, Any]]) -> YandexTransportResponse:
    return YandexTransportResponse(
        status=200,
        payload={
            "id": response_id,
            "status": "completed",
            "output": output,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 3},
            },
        },
    )


def final_json(*, source_id: str | None = None) -> str:
    facts: list[dict[str, Any]] = []
    if source_id is not None:
        facts.append(
            {
                "key": "ownship.heading_deg",
                "value": 137,
                "kind": "authoritative",
                "unit": "deg",
                "source": {"context_type": "tool_result", "reference_id": source_id},
            }
        )
    return json.dumps(
        {
            "capability": "world.ownship.read" if source_id else None,
            "presentation_mode": "naturalize",
            "authoritative_facts": facts,
            "derived_results": [],
            "recommendation": "Current heading is 137 degrees.",
            "assumptions": [],
            "unavailable_inputs": [],
            "warnings": [],
            "verbatim_text": None,
        }
    )


def message(text: str) -> list[dict[str, Any]]:
    return [{"type": "message", "content": [{"type": "output_text", "text": text}]}]


def test_config_reuses_secure_key_and_folder_without_workflow(tmp_path: Path) -> None:
    CloudVoiceConfigStore(tmp_path).save(
        CloudVoiceConfig(
            yandex_folder_id="folder-123",
            qwen_workspace_id="realtime-workflow-must-not-leak",
        )
    )
    backend = MemoryCredentialBackend()
    store = VoiceCredentialStore(backend)
    store.save(VoiceCredential.YANDEX_API_KEY, "secure-key")

    loaded = load_yandex_qwen_planner_config(tmp_path, credential_store=store)

    assert loaded.folder_id == "folder-123"
    assert loaded.model_uri == "gpt://folder-123/qwen3.6-35b-a3b"
    assert "secure-key" not in repr(loaded)
    assert "workflow" not in loaded.model_dump()


def test_missing_secure_key_and_invalid_folder_fail_closed(tmp_path: Path) -> None:
    store = VoiceCredentialStore(MemoryCredentialBackend())
    with pytest.raises(YandexPlannerConfigurationError, match="not configured"):
        load_yandex_qwen_planner_config(tmp_path, credential_store=store)
    store.save(VoiceCredential.YANDEX_API_KEY, "secure-key")
    with pytest.raises(YandexPlannerConfigurationError, match="invalid"):
        load_yandex_qwen_planner_config(tmp_path, credential_store=store)


def test_model_and_endpoint_are_fixed_to_live_verified_contract() -> None:
    assert config().model_id == QWEN_MODEL_ID
    with pytest.raises(ValidationError):
        YandexQwenPlannerConfig(folder_id="folder-123", api_key="x", model_id="other")
    with pytest.raises(ValidationError):
        YandexQwenPlannerConfig(folder_id="folder-123", api_key="x", endpoint="https://example.test")


def test_transport_accumulates_all_json_chunks_before_parsing() -> None:
    class ChunkedContent:
        async def iter_chunked(self, _size: int):  # type: ignore[no-untyped-def]
            yield b'{"id":"resp-'
            yield b'chunked","status":"completed"}'

    assert asyncio.run(_read_bounded_json(ChunkedContent())) == {
        "id": "resp-chunked",
        "status": "completed",
    }


def test_bounded_reader_rejects_oversize_and_non_object_json() -> None:
    class Content:
        def __init__(self, chunks: list[bytes]) -> None:
            self.chunks = chunks

        async def iter_chunked(self, _size: int):  # type: ignore[no-untyped-def]
            for chunk in self.chunks:
                yield chunk

    assert asyncio.run(_read_bounded_json(Content([b"[]"]))) is None
    assert asyncio.run(_read_bounded_json(Content([b"not-json"]))) is None
    assert asyncio.run(_read_bounded_json(Content([]))) is None
    with pytest.raises(YandexPlannerTransportError) as error:
        asyncio.run(_read_bounded_json(Content([b"x" * 1_000_001])))
    assert error.value.category is YandexFailureCategory.PROTOCOL


def test_aiohttp_transport_builds_private_reusable_session_and_reads_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class Content:
        async def iter_chunked(self, _size: int):  # type: ignore[no-untyped-def]
            yield b'{"id":"resp-fake","status":"completed"}'

    class Response:
        status = 200
        content = Content()

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def read(self) -> bytes:
            return b""

    class Session:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def post(self, endpoint: str, *, json: Mapping[str, Any]) -> Response:
            captured["endpoint"] = endpoint
            captured["payload"] = json
            return Response()

        def delete(self, endpoint: str) -> Response:
            captured["delete_endpoint"] = endpoint
            return Response()

        async def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr("orion.yandex_qwen_planner.aiohttp.ClientSession", Session)
    transport = object.__new__(AiohttpYandexResponsesTransport)
    transport._config = config()  # type: ignore[attr-defined]
    transport._session = None  # type: ignore[attr-defined]

    async def exercise() -> None:
        result = await transport._create({"input": "bounded"})  # type: ignore[attr-defined]
        assert result.status == 200
        assert result.payload == {"id": "resp-fake", "status": "completed"}
        await transport._delete("resp-fake")  # type: ignore[attr-defined]
        await transport._session.close()  # type: ignore[attr-defined,union-attr]

    asyncio.run(exercise())
    assert captured["headers"]["Authorization"] == "Api-Key unit-key"
    assert captured["headers"]["OpenAI-Project"] == "folder-123"
    assert captured["endpoint"].endswith("/v1/responses")
    assert captured["delete_endpoint"].endswith("/v1/responses/resp-fake")
    assert captured["closed"] is True


def test_transport_wait_maps_cancel_deadline_and_client_failure() -> None:
    async def delayed() -> YandexTransportResponse:
        await asyncio.sleep(10)
        return YandexTransportResponse(status=200, payload={})

    transport = AiohttpYandexResponsesTransport(config())
    cancelled = PlannerCancellationToken()
    cancelled.cancel()
    with pytest.raises(YandexPlannerTransportError) as error:
        transport._await(  # type: ignore[attr-defined]
            delayed(), deadline=NOW + timedelta(minutes=1), cancellation=cancelled
        )
    assert error.value.category is YandexFailureCategory.CANCELLED
    with pytest.raises(YandexPlannerTransportError) as error:
        transport._await(  # type: ignore[attr-defined]
            delayed(),
            deadline=datetime.now(UTC) - timedelta(seconds=1),
            cancellation=PlannerCancellationToken(),
        )
    assert error.value.category is YandexFailureCategory.TIMEOUT

    async def unavailable() -> YandexTransportResponse:
        import aiohttp

        raise aiohttp.ClientConnectionError("safe test")

    with pytest.raises(YandexPlannerTransportError) as error:
        transport._await(  # type: ignore[attr-defined]
            unavailable(), deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
        )
    assert error.value.category is YandexFailureCategory.UNAVAILABLE
    transport.close()
    transport.close()


def test_http_failure_classification_is_deterministic() -> None:
    expected = {
        401: YandexFailureCategory.AUTHENTICATION,
        403: YandexFailureCategory.PERMISSION,
        404: YandexFailureCategory.MODEL_UNAVAILABLE,
        429: YandexFailureCategory.RATE_LIMITED,
        504: YandexFailureCategory.TIMEOUT,
        503: YandexFailureCategory.UNAVAILABLE,
        400: YandexFailureCategory.PROTOCOL,
    }
    assert {status: _http_failure(status) for status in expected} == expected


def test_structured_response_is_adapted_to_semantic_response_and_cleaned_up() -> None:
    transport = FakeTransport([response("resp-final", message(final_json()))])
    provider = YandexQwenPlannerProvider(config(), transport_factory=lambda _config: transport)
    run = provider.start(provider_request())

    event = run.next_event(
        deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
    )

    assert isinstance(event, PlannerFinalResponseEvent)
    assert event.response.interaction_id == INTERACTION_ID
    assert event.response.recommendation == "Current heading is 137 degrees."
    assert event.usage is not None
    assert event.usage.input_tokens == 10
    assert event.usage.output_tokens == 20
    assert event.usage.cached_tokens == 3
    assert transport.deleted == ["resp-final"]
    assert transport.closed
    payload_text = json.dumps(transport.payloads)
    assert "unit-key" not in payload_text
    assert "workflow" not in payload_text


@pytest.mark.parametrize(
    ("output", "status"),
    [
        ([{"type": "unknown"}], 200),
        (message("not-json"), 200),
        (message(json.dumps({"recommendation": "missing fields"})), 200),
    ],
)
def test_malformed_and_unknown_outputs_fail_safely(
    output: list[dict[str, Any]], status: int
) -> None:
    transport = FakeTransport([response("resp-bad", output)])
    run = YandexQwenPlannerProvider(
        config(), transport_factory=lambda _config: transport
    ).start(provider_request())
    event = run.next_event(
        deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
    )
    assert isinstance(event, PlannerFailedEvent)
    assert event.error.code is PlannerErrorCode.PROVIDER_PROTOCOL_ERROR
    assert transport.closed


def test_missing_response_id_and_incomplete_response_fail_safely() -> None:
    missing_id = YandexTransportResponse(
        status=200, payload={"status": "completed", "output": message(final_json())}
    )
    incomplete = YandexTransportResponse(
        status=200, payload={"id": "resp-incomplete", "status": "incomplete", "output": []}
    )
    for item in (missing_id, incomplete):
        transport = FakeTransport([item])
        event = YandexQwenPlannerProvider(
            config(), transport_factory=lambda _config, t=transport: t
        ).start(provider_request()).next_event(
            deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
        )
        assert isinstance(event, PlannerFailedEvent)


def test_function_call_translation_and_previous_response_continuation() -> None:
    call = {
        "type": "function_call",
        "name": _provider_tool_name("orion.world.ownship.get"),
        "call_id": "call-1",
        "arguments": "{}",
    }
    transport = FakeTransport(
        [
            response("resp-tools", [{"type": "reasoning"}, call]),
            response("resp-final", message(final_json(source_id="call-1"))),
        ]
    )
    provider = YandexQwenPlannerProvider(config(), transport_factory=lambda _config: transport)
    run = provider.start(provider_request("world.ownship.read"))
    tool_event = run.next_event(
        deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
    )
    assert isinstance(tool_event, PlannerToolCallsEvent)
    assert tool_event.calls[0].call_id == "call-1"
    result = gateway().execute  # prove provider cannot execute this callable directly
    assert result is not None

    # IA-4 normally supplies this exact result after executing the request through IA-3.
    from orion.tool_gateway_contracts import ExecutionContext, ToolCall

    tool_result = gateway().execute(
        ToolCall(
            call_id="call-1",
            name="orion.world.ownship.get",
            version="1.0",
            context=ExecutionContext(
                actor_id="pilot-1",
                allowed_capabilities=(CapabilityId("world.ownship.read"),),
            ),
        )
    )
    run.continue_with_tool_results((tool_result,))
    final_event = run.next_event(
        deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
    )
    assert isinstance(final_event, PlannerFinalResponseEvent)
    continuation = transport.payloads[1]
    assert continuation["previous_response_id"] == "resp-tools"
    assert continuation["tool_choice"] == "auto"
    output = json.loads(continuation["input"][0]["output"])
    assert output["status"] == "completed"
    assert "snapshot" not in output["data"]
    assert any(
        item["key"] == "ownship.heading_deg" and item["value"] == 137
        for item in output["data"]["facts"]
    )
    assert "authoritative" in output["provenance"]["authorities"]
    assert transport.deleted == ["resp-tools", "resp-final"]


def test_tool_schema_is_strict_and_continuation_can_request_another_round() -> None:
    first = {
        "type": "function_call",
        "name": _provider_tool_name("orion.test.ping"),
        "call_id": "call-first",
        "arguments": '{"message":null}',
    }
    second = {
        "type": "function_call",
        "name": _provider_tool_name("orion.world.ownship.get"),
        "call_id": "call-second",
        "arguments": "{}",
    }
    transport = FakeTransport([response("resp-first", [first]), response("resp-second", [second])])
    allowed = (CapabilityId("test.ping"), CapabilityId("world.ownship.read"))
    definitions = tuple(item for item in gateway().definitions() if item.capability in allowed)
    request = PlannerProviderRequest(
        planner_task_id="planner-rounds",
        interaction=interaction("test.ping", "world.ownship.read"),
        allowed_capabilities=allowed,
        available_tools=definitions,
        deadline=NOW + timedelta(minutes=1),
        retry_policy=ProviderRetryPolicy(max_attempts=1),
    )
    run = YandexQwenPlannerProvider(config(), transport_factory=lambda _config: transport).start(request)
    event = run.next_event(deadline=request.deadline, cancellation=PlannerCancellationToken())
    assert isinstance(event, PlannerToolCallsEvent)
    from orion.tool_gateway_contracts import ExecutionContext, ToolCall

    result = gateway().execute(
        ToolCall(
            call_id="call-first",
            name="orion.test.ping",
            version="1.0",
            arguments=event.calls[0].arguments,
            context=ExecutionContext(actor_id="pilot", allowed_capabilities=allowed),
        )
    )
    run.continue_with_tool_results((result,))
    event = run.next_event(deadline=request.deadline, cancellation=PlannerCancellationToken())
    assert isinstance(event, PlannerToolCallsEvent)
    ping_schema = next(
        item["parameters"]
        for item in transport.payloads[0]["tools"]
        if item["name"] == _provider_tool_name("orion.test.ping")
    )
    assert ping_schema["required"] == ["message"]
    assert "default" not in json.dumps(ping_schema)
    assert transport.payloads[0]["tool_choice"] == "required"
    assert transport.payloads[1]["tool_choice"] == "auto"
    run.cancel()


@pytest.mark.parametrize(
    "call",
    [
        {"type": "function_call", "name": "orion_unknown_get", "call_id": "call-1", "arguments": "{}"},
        {"type": "function_call", "name": _provider_tool_name("orion.world.ownship.get"), "call_id": "call-1", "arguments": "[]"},
        {"type": "function_call", "name": _provider_tool_name("orion.world.ownship.get"), "call_id": "call-1", "arguments": "{"},
    ],
)
def test_invalid_or_unexposed_tool_call_fails_closed(call: dict[str, Any]) -> None:
    transport = FakeTransport([response("resp-bad-tool", [call])])
    event = YandexQwenPlannerProvider(
        config(), transport_factory=lambda _config: transport
    ).start(provider_request("world.ownship.read")).next_event(
        deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
    )
    assert isinstance(event, PlannerFailedEvent)
    assert transport.closed


def test_single_exposed_tool_is_selected_with_live_verified_choice_shape() -> None:
    call = {
        "type": "function_call",
        "name": _provider_tool_name("orion.world.ownship.get"),
        "call_id": "call-only",
        "arguments": "{}",
    }
    transport = FakeTransport([response("resp-only", [call])])
    run = YandexQwenPlannerProvider(config(), transport_factory=lambda _config: transport).start(
        provider_request("world.ownship.read")
    )
    event = run.next_event(
        deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
    )
    assert isinstance(event, PlannerToolCallsEvent)
    assert transport.payloads[0]["tool_choice"] == {
        "type": "function",
        "name": _provider_tool_name("orion.world.ownship.get"),
    }
    assert "text" not in transport.payloads[0]
    run.cancel()


def test_retry_is_bounded_to_transient_failures() -> None:
    transport = FakeTransport(
        [YandexTransportResponse(status=429, payload={}), response("resp-ok", message(final_json()))]
    )
    provider = YandexQwenPlannerProvider(config(), transport_factory=lambda _config: transport)
    event = provider.start(provider_request()).next_event(
        deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
    )
    assert isinstance(event, PlannerFinalResponseEvent)
    assert len(transport.payloads) == 2
    assert any(item.stage == "retry" for item in provider.diagnostic_snapshot())

    deterministic = FakeTransport(
        [YandexTransportResponse(status=401, payload={}), response("never", message(final_json()))]
    )
    event = YandexQwenPlannerProvider(
        config(), transport_factory=lambda _config: deterministic
    ).start(provider_request()).next_event(
        deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
    )
    assert isinstance(event, PlannerFailedEvent)
    assert len(deterministic.payloads) == 1


def test_transport_timeout_is_provider_timeout_and_diagnostics_are_private() -> None:
    transport = FakeTransport(
        [YandexPlannerTransportError(YandexFailureCategory.TIMEOUT)] * 2
    )
    diagnostics = YandexPlannerDiagnostics(max_events=20)
    provider = YandexQwenPlannerProvider(
        config(), transport_factory=lambda _config: transport, diagnostics=diagnostics
    )
    event = provider.start(provider_request()).next_event(
        deadline=NOW + timedelta(minutes=1), cancellation=PlannerCancellationToken()
    )
    assert isinstance(event, PlannerFailedEvent)
    assert event.error.code is PlannerErrorCode.PROVIDER_TIMEOUT
    evidence = repr(diagnostics.snapshot())
    assert "unit-key" not in evidence
    assert "Where am I" not in evidence
    assert "Authorization" not in evidence


def test_real_ia4_ia3_ia2_vertical_uses_only_allowed_tool_once() -> None:
    call = {
        "type": "function_call",
        "name": _provider_tool_name("orion.world.ownship.get"),
        "call_id": "call-vertical",
        "arguments": "{}",
    }
    transport = FakeTransport(
        [
            response("resp-tool", [call]),
            response("resp-semantic", message(final_json(source_id="call-vertical"))),
        ]
    )
    provider = YandexQwenPlannerProvider(config(), transport_factory=lambda _config: transport)
    task_gateway = gateway()
    runner = PlannerTaskRunner(
        gateway=task_gateway,
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
        task_id_factory=lambda: "planner-vertical",
    )
    result = runner.execute(
        interaction("world.ownship.read"),
        provider,
        PlannerExecutionPolicy(
            actor_id="pilot-1",
            provider_id=QWEN_PROVIDER_ID,
            permissions=("world.read",),
            core_instructions=("Use only completed Core tool results.",),
            deadline=NOW + timedelta(minutes=1),
            provider_retry=ProviderRetryPolicy(max_attempts=2),
        ),
    )

    assert result.response is not None
    assert result.response.authoritative_facts[0].value == 137
    assert result.task.requested_call_ids == ("call-vertical",)
    assert len(result.task.completed_tool_receipts) == 1
    assert [tool["name"] for tool in transport.payloads[0]["tools"]] == [
        _provider_tool_name("orion.world.ownship.get")
    ]
