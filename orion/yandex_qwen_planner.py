"""IA-5 Qwen3.6 adapter for the provider-neutral IA-4 planner boundary.

The module intentionally owns only provider translation and transport.  Core
keeps tool policy, execution, provenance validation and semantic acceptance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from orion.interaction_contracts import (
    CapabilityId,
    ContextReference,
    PresentationMode,
    SemanticFact,
    SemanticFactKind,
    SemanticInputIssue,
    SemanticResponse,
)
from orion.launcher_cloud_voice_sections import CloudVoiceConfigStore
from orion.mixed_conversation import MixedConversationDecomposition
from orion.planner import PlannerCancellationToken, PlannerProvider, PlannerRun
from orion.planner_contracts import (
    PlannerError,
    PlannerErrorCategory,
    PlannerErrorCode,
    PlannerEvent,
    PlannerFailedEvent,
    PlannerFinalResponseEvent,
    PlannerProviderRequest,
    PlannerToolCallsEvent,
    PlannerToolRequest,
    PlannerUsage,
)
from orion.tool_gateway import (
    GeometryArguments,
    MissionUnitsArguments,
    NoArguments,
    PingArguments,
)
from orion.tool_gateway_contracts import ToolArguments, ToolDefinition, ToolResult
from orion.windows_credentials import (
    VoiceCredential,
    VoiceCredentialStore,
    default_voice_credential_store,
)


logger = logging.getLogger(__name__)

YANDEX_RESPONSES_ENDPOINT = "https://ai.api.cloud.yandex.net/v1/responses"
QWEN_MODEL_ID = "qwen3.6-35b-a3b"
QWEN_PROVIDER_ID = "yandex.qwen3.6-35b-a3b"
_FOLDER_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
_MAX_PROVIDER_BODY_BYTES = 1_000_000
_MAX_OUTPUT_TOKENS = 8192


class YandexPlannerConfigurationError(RuntimeError):
    """Safe configuration failure which never includes credential material."""


class YandexPlannerTransportError(RuntimeError):
    """Safe transport failure classified without raw provider content."""

    def __init__(self, category: YandexFailureCategory, *, http_status: int | None = None) -> None:
        super().__init__(category.value)
        self.category = category
        self.http_status = http_status


class YandexFailureCategory(StrEnum):
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    MODEL_UNAVAILABLE = "model_unavailable"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    PROTOCOL = "protocol_error"
    INVALID_RESPONSE = "invalid_response"
    INVALID_TOOL_CALL = "invalid_tool_call"
    STRUCTURED_OUTPUT = "structured_output_failure"
    CANCELLED = "cancelled"


class YandexQwenPlannerConfig(BaseModel):
    """Validated secret-bearing runtime configuration; repr hides the key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    folder_id: str
    api_key: str = Field(repr=False, min_length=1)
    model_id: str = QWEN_MODEL_ID
    endpoint: str = YANDEX_RESPONSES_ENDPOINT
    reasoning_effort: str = "low"
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    read_timeout_seconds: float = Field(default=45.0, gt=0, le=120)

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str) -> str:
        normalized = value.strip()
        if _FOLDER_ID.fullmatch(normalized) is None:
            raise ValueError("Yandex Folder ID is missing or invalid")
        return normalized

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Yandex API key is missing")
        return normalized

    @field_validator("model_id")
    @classmethod
    def require_qwen_model(cls, value: str) -> str:
        if value != QWEN_MODEL_ID:
            raise ValueError("Unsupported IA-5 model identifier")
        return value

    @field_validator("endpoint")
    @classmethod
    def require_endpoint(cls, value: str) -> str:
        if value != YANDEX_RESPONSES_ENDPOINT:
            raise ValueError("Unsupported IA-5 Responses endpoint")
        return value

    @field_validator("reasoning_effort")
    @classmethod
    def require_low_effort(cls, value: str) -> str:
        if value != "low":
            raise ValueError("IA-5 uses the live-verified low reasoning default")
        return value

    @property
    def model_uri(self) -> str:
        return f"gpt://{self.folder_id}/{self.model_id}"


def load_yandex_qwen_planner_config(
    runtime_dir: Path,
    *,
    credential_store: VoiceCredentialStore | None = None,
) -> YandexQwenPlannerConfig:
    """Reuse existing non-secret Folder ID and Windows secure API-key boundary."""

    config = CloudVoiceConfigStore(runtime_dir).load()
    store = credential_store or default_voice_credential_store()
    api_key = store.load(VoiceCredential.YANDEX_API_KEY)
    if not api_key.strip():
        raise YandexPlannerConfigurationError("Yandex API key is not configured securely")
    try:
        return YandexQwenPlannerConfig(folder_id=config.yandex_folder_id, api_key=api_key)
    except ValidationError as exc:
        raise YandexPlannerConfigurationError("Yandex planner configuration is invalid") from exc


@dataclass(frozen=True, slots=True)
class YandexTransportResponse:
    status: int
    payload: Mapping[str, Any] | None


class YandexResponsesTransport(Protocol):
    def create(
        self,
        payload: Mapping[str, Any],
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken,
    ) -> YandexTransportResponse: ...

    def delete(self, response_id: str) -> None: ...

    def close(self) -> None: ...


class AiohttpYandexResponsesTransport:
    """One reusable ClientSession on a dedicated loop for one bounded planner run."""

    def __init__(self, config: YandexQwenPlannerConfig) -> None:
        self._config = config
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="orion-yandex-responses",
            daemon=True,
        )
        self._session: aiohttp.ClientSession | None = None
        self._closed = False
        self._thread.start()
        if not self._ready.wait(5):
            raise YandexPlannerTransportError(YandexFailureCategory.UNAVAILABLE)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(
                total=self._config.read_timeout_seconds,
                connect=self._config.connect_timeout_seconds,
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Authorization": f"Api-Key {self._config.api_key}",
                    "OpenAI-Project": self._config.folder_id,
                    "Content-Type": "application/json",
                },
            )
        return self._session

    async def _create(self, payload: Mapping[str, Any]) -> YandexTransportResponse:
        session = await self._get_session()
        async with session.post(self._config.endpoint, json=payload) as response:
            parsed = await _read_bounded_json(response.content)
            return YandexTransportResponse(status=response.status, payload=parsed)

    def create(
        self,
        payload: Mapping[str, Any],
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken,
    ) -> YandexTransportResponse:
        return self._await(self._create(payload), deadline=deadline, cancellation=cancellation)

    async def _delete(self, response_id: str) -> None:
        session = await self._get_session()
        url = f"{self._config.endpoint}/{response_id}"
        async with session.delete(url) as response:
            await response.read()

    def delete(self, response_id: str) -> None:
        if self._closed:
            return
        future = asyncio.run_coroutine_threadsafe(self._delete(response_id), self._loop)
        try:
            future.result(timeout=min(5.0, self._config.read_timeout_seconds))
        except Exception:
            future.cancel()
            logger.warning("IA-5 provider response cleanup did not complete")

    def _await(
        self,
        coroutine: Any,
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken,
    ) -> YandexTransportResponse:
        future: Future[YandexTransportResponse] = asyncio.run_coroutine_threadsafe(
            coroutine,
            self._loop,
        )
        while True:
            if cancellation.cancelled:
                future.cancel()
                raise YandexPlannerTransportError(YandexFailureCategory.CANCELLED)
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                future.cancel()
                raise YandexPlannerTransportError(YandexFailureCategory.TIMEOUT)
            try:
                return future.result(timeout=min(0.05, remaining))
            except FutureTimeoutError:
                continue
            except aiohttp.ClientError as exc:
                raise YandexPlannerTransportError(YandexFailureCategory.UNAVAILABLE) from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        async def close_session() -> None:
            if self._session is not None:
                await self._session.close()

        future = asyncio.run_coroutine_threadsafe(close_session(), self._loop)
        try:
            future.result(timeout=5)
        except Exception:
            future.cancel()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


class YandexDiagnosticStage(StrEnum):
    REQUEST_STARTED = "request_started"
    RESPONSE_RECEIVED = "response_received"
    TOOL_CALL = "tool_call"
    CONTINUATION = "continuation"
    RETRY = "retry"
    FINAL_ACCEPTED = "final_accepted"
    FAILED = "failed"
    CLEANUP = "cleanup"


@dataclass(frozen=True, slots=True)
class YandexPlannerDiagnostic:
    stage: YandexDiagnosticStage
    planner_task_id: str
    model_id: str
    attempt: int | None = None
    response_id: str | None = None
    latency_ms: float | None = None
    http_status: int | None = None
    tool_name: str | None = None
    failure_category: YandexFailureCategory | None = None


class YandexPlannerDiagnostics:
    """Bounded scalar-only provider diagnostics; no prompts, bodies or secrets."""

    def __init__(self, max_events: int = 500) -> None:
        if max_events <= 0:
            raise ValueError("Diagnostic bound must be positive")
        self._events: deque[YandexPlannerDiagnostic] = deque(maxlen=max_events)
        self._lock = threading.RLock()

    def record(self, event: YandexPlannerDiagnostic) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> tuple[YandexPlannerDiagnostic, ...]:
        with self._lock:
            return tuple(self._events)


TransportFactory = Callable[[YandexQwenPlannerConfig], YandexResponsesTransport]


class YandexQwenPlannerProvider(PlannerProvider):
    """Real Qwen3.6 provider adapter conforming to the unchanged IA-4 protocol."""

    provider_id = QWEN_PROVIDER_ID

    def __init__(
        self,
        config: YandexQwenPlannerConfig,
        *,
        transport_factory: TransportFactory = AiohttpYandexResponsesTransport,
        diagnostics: YandexPlannerDiagnostics | None = None,
    ) -> None:
        self._config = config
        self._transport_factory = transport_factory
        self._diagnostics = diagnostics or YandexPlannerDiagnostics()

    def start(self, request: PlannerProviderRequest) -> PlannerRun:
        return YandexQwenPlannerRun(
            request=request,
            config=self._config,
            transport=self._transport_factory(self._config),
            diagnostics=self._diagnostics,
        )

    def diagnostic_snapshot(self) -> tuple[YandexPlannerDiagnostic, ...]:
        return self._diagnostics.snapshot()


class _SemanticDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: CapabilityId | None
    presentation_mode: PresentationMode
    authoritative_facts: tuple[SemanticFact, ...]
    derived_results: tuple[SemanticFact, ...]
    recommendation: str | None
    assumptions: tuple[str, ...]
    unavailable_inputs: tuple[SemanticInputIssue, ...]
    warnings: tuple[str, ...]
    verbatim_text: str | None


class YandexQwenPlannerRun(PlannerRun):
    def __init__(
        self,
        *,
        request: PlannerProviderRequest,
        config: YandexQwenPlannerConfig,
        transport: YandexResponsesTransport,
        diagnostics: YandexPlannerDiagnostics,
    ) -> None:
        self._request = request
        self._config = config
        self._transport = transport
        self._diagnostics = diagnostics
        self._previous_response_id: str | None = None
        self._response_ids: list[str] = []
        self._pending_results: tuple[ToolResult, ...] | None = None
        self._started = False
        self._terminal = False
        self._closed = False
        self._event_sequence = 0

    def next_event(
        self,
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken,
    ) -> PlannerEvent:
        if self._terminal:
            raise RuntimeError("Provider run is already terminal")
        if cancellation.cancelled:
            self.cancel()
            return self._failed(YandexFailureCategory.CANCELLED)
        payload = self._continuation_payload() if self._started else self._initial_payload()
        self._started = True
        started = time.perf_counter()
        response, attempts = self._request_with_retry(
            payload,
            deadline=deadline,
            cancellation=cancellation,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        self._diagnostic(
            YandexDiagnosticStage.RESPONSE_RECEIVED,
            attempt=attempts,
            latency_ms=latency_ms,
            http_status=response.status,
        )
        if response.status != 200:
            category = _http_failure(response.status)
            return self._finish_failed(category, http_status=response.status)
        body = response.payload
        if body is None:
            return self._finish_failed(YandexFailureCategory.INVALID_RESPONSE)
        response_id = body.get("id")
        if not isinstance(response_id, str) or not _safe_provider_id(response_id):
            return self._finish_failed(YandexFailureCategory.INVALID_RESPONSE)
        self._previous_response_id = response_id
        self._response_ids.append(response_id)
        self._diagnostic(YandexDiagnosticStage.RESPONSE_RECEIVED, response_id=response_id)
        usage = _parse_usage(body, self._config.model_id, response_id, attempts, latency_ms)
        status = body.get("status")
        if status != "completed":
            return self._finish_failed(YandexFailureCategory.INVALID_RESPONSE, usage=usage)
        try:
            event = self._translate_completed(body, usage)
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError):
            return self._finish_failed(YandexFailureCategory.INVALID_RESPONSE, usage=usage)
        if isinstance(event, PlannerFinalResponseEvent):
            self._terminal = True
            self._diagnostic(
                YandexDiagnosticStage.FINAL_ACCEPTED,
                response_id=response_id,
                latency_ms=latency_ms,
            )
            self._cleanup()
        return event

    def continue_with_tool_results(self, results: tuple[ToolResult, ...]) -> None:
        if self._terminal or self._previous_response_id is None or not results:
            raise RuntimeError("Provider continuation is not available")
        if self._pending_results is not None:
            raise RuntimeError("Provider continuation results are already pending")
        self._pending_results = results
        self._diagnostic(YandexDiagnosticStage.CONTINUATION)

    def cancel(self) -> None:
        self._terminal = True
        self._cleanup()

    def _initial_payload(self) -> dict[str, Any]:
        tools = [_provider_tool(item) for item in self._request.available_tools]
        payload: dict[str, Any] = {
            "model": self._config.model_uri,
            "instructions": _instructions(self._request),
            "input": self._request.interaction.text,
            "reasoning": {"effort": self._config.reasoning_effort},
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "parallel_tool_calls": False,
            "store": bool(tools),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = (
                {"type": "function", "name": tools[0]["name"]}
                if len(tools) == 1
                else "required"
            )
        else:
            payload["text"] = {"format": _semantic_format()}
        return payload

    def _continuation_payload(self) -> dict[str, Any]:
        if self._previous_response_id is None or self._pending_results is None:
            raise RuntimeError("Tool results are required before continuation")
        results = self._pending_results
        self._pending_results = None
        tools = [_provider_tool(item) for item in self._request.available_tools]
        payload: dict[str, Any] = {
            "model": self._config.model_uri,
            "previous_response_id": self._previous_response_id,
            "instructions": _instructions(self._request),
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": result.call_id,
                    "output": json.dumps(_safe_tool_result(result), ensure_ascii=True),
                }
                for result in results
            ],
            "reasoning": {"effort": self._config.reasoning_effort},
            "text": {"format": _semantic_format()},
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "parallel_tool_calls": False,
            "store": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _request_with_retry(
        self,
        payload: Mapping[str, Any],
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken,
    ) -> tuple[YandexTransportResponse, int]:
        attempts = 0
        while attempts < self._request.retry_policy.max_attempts:
            attempts += 1
            self._diagnostic(YandexDiagnosticStage.REQUEST_STARTED, attempt=attempts)
            try:
                response = self._transport.create(
                    payload,
                    deadline=deadline,
                    cancellation=cancellation,
                )
            except YandexPlannerTransportError as exc:
                if exc.category is YandexFailureCategory.CANCELLED:
                    return YandexTransportResponse(status=499, payload=None), attempts
                retryable = exc.category in {
                    YandexFailureCategory.TIMEOUT,
                    YandexFailureCategory.UNAVAILABLE,
                }
                if retryable and attempts < self._request.retry_policy.max_attempts:
                    self._diagnostic(
                        YandexDiagnosticStage.RETRY,
                        attempt=attempts,
                        failure_category=exc.category,
                    )
                    continue
                status = 598 if exc.category is YandexFailureCategory.TIMEOUT else 599
                return YandexTransportResponse(status=status, payload=None), attempts
            if response.status in {429, 500, 502, 503, 504} and attempts < self._request.retry_policy.max_attempts:
                self._diagnostic(
                    YandexDiagnosticStage.RETRY,
                    attempt=attempts,
                    http_status=response.status,
                    failure_category=_http_failure(response.status),
                )
                continue
            return response, attempts
        raise RuntimeError("Bounded provider retry loop exhausted unexpectedly")

    def _translate_completed(
        self,
        body: Mapping[str, Any],
        usage: PlannerUsage,
    ) -> PlannerEvent:
        output = body.get("output")
        if not isinstance(output, list):
            raise ValueError("Provider output must be an array")
        calls: list[PlannerToolRequest] = []
        text_parts: list[str] = []
        exposed = {_provider_tool_name(item.name): item for item in self._request.available_tools}
        for item in output:
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                raise ValueError("Invalid provider output item")
            item_type = item["type"]
            if item_type == "reasoning":
                continue
            if item_type == "function_call":
                name = item.get("name")
                call_id = item.get("call_id")
                arguments = item.get("arguments")
                if (
                    not isinstance(name, str)
                    or name not in exposed
                    or not isinstance(call_id, str)
                    or not _safe_provider_id(call_id)
                    or not isinstance(arguments, str)
                ):
                    raise ValueError("Invalid provider function call")
                parsed = json.loads(arguments)
                if not isinstance(parsed, dict):
                    raise ValueError("Provider tool arguments must be an object")
                calls.append(
                    PlannerToolRequest(
                        call_id=call_id,
                        name=exposed[name].name,
                        version=exposed[name].version,
                        arguments=ToolArguments.model_validate(parsed),
                    )
                )
                self._diagnostic(
                    YandexDiagnosticStage.TOOL_CALL,
                    tool_name=exposed[name].name,
                )
                continue
            if item_type == "message":
                content = item.get("content")
                if not isinstance(content, list):
                    raise ValueError("Provider message content must be an array")
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        value = part.get("text")
                        if isinstance(value, str):
                            text_parts.append(value)
                        else:
                            raise ValueError("Provider output text is invalid")
                    else:
                        raise ValueError("Unknown provider message content")
                continue
            raise ValueError("Unknown provider output item")
        if calls and text_parts:
            raise ValueError("Mixed tool and final output is not accepted")
        if calls:
            if len(calls) > 8 or len({call.call_id for call in calls}) != len(calls):
                raise ValueError("Provider tool call batch is invalid")
            return PlannerToolCallsEvent(
                event_id=self._event_id("tools"),
                calls=tuple(calls),
                usage=usage,
            )
        if not text_parts:
            raise ValueError("Completed response contains no accepted output")
        draft = _SemanticDraft.model_validate_json("".join(text_parts))
        response = SemanticResponse(
            interaction_id=self._request.interaction.interaction_id,
            **draft.model_dump(),
        )
        return PlannerFinalResponseEvent(
            event_id=self._event_id("final"),
            response=response,
            usage=usage,
        )

    def _finish_failed(
        self,
        category: YandexFailureCategory,
        *,
        http_status: int | None = None,
        usage: PlannerUsage | None = None,
    ) -> PlannerFailedEvent:
        self._terminal = True
        event = self._failed(category, usage=usage)
        self._diagnostic(
            YandexDiagnosticStage.FAILED,
            http_status=http_status,
            failure_category=category,
        )
        self._cleanup()
        return event

    def _failed(
        self,
        category: YandexFailureCategory,
        *,
        usage: PlannerUsage | None = None,
    ) -> PlannerFailedEvent:
        code = {
            YandexFailureCategory.TIMEOUT: PlannerErrorCode.PROVIDER_TIMEOUT,
            YandexFailureCategory.RATE_LIMITED: PlannerErrorCode.PROVIDER_UNAVAILABLE,
            YandexFailureCategory.UNAVAILABLE: PlannerErrorCode.PROVIDER_UNAVAILABLE,
            YandexFailureCategory.MODEL_UNAVAILABLE: PlannerErrorCode.PROVIDER_UNAVAILABLE,
        }.get(category, PlannerErrorCode.PROVIDER_PROTOCOL_ERROR)
        return PlannerFailedEvent(
            event_id=self._event_id("failed"),
            error=PlannerError(
                code=code,
                category=(
                    PlannerErrorCategory.PROVIDER
                    if code is not PlannerErrorCode.PROVIDER_PROTOCOL_ERROR
                    else PlannerErrorCategory.PROTOCOL
                ),
                message="Yandex planner request failed safely.",
                retryable=code is PlannerErrorCode.PROVIDER_UNAVAILABLE,
            ),
            usage=usage,
        )

    def _event_id(self, suffix: str) -> str:
        self._event_sequence += 1
        seed = f"{self._request.planner_task_id}:{self._event_sequence}:{suffix}"
        return f"ia5-{hashlib.sha256(seed.encode()).hexdigest()[:24]}"

    def _cleanup(self) -> None:
        if self._closed:
            return
        for response_id in self._response_ids:
            self._transport.delete(response_id)
        self._response_ids.clear()
        self._transport.close()
        self._closed = True
        self._diagnostic(YandexDiagnosticStage.CLEANUP)

    def _diagnostic(
        self,
        stage: YandexDiagnosticStage,
        *,
        attempt: int | None = None,
        response_id: str | None = None,
        latency_ms: float | None = None,
        http_status: int | None = None,
        tool_name: str | None = None,
        failure_category: YandexFailureCategory | None = None,
    ) -> None:
        self._diagnostics.record(
            YandexPlannerDiagnostic(
                stage=stage,
                planner_task_id=self._request.planner_task_id,
                model_id=self._config.model_id,
                attempt=attempt,
                response_id=response_id,
                latency_ms=latency_ms,
                http_status=http_status,
                tool_name=tool_name,
                failure_category=failure_category,
            )
        )


_INPUT_MODELS: dict[str, type[BaseModel]] = {
    MixedConversationDecomposition.schema_identity: MixedConversationDecomposition,
    NoArguments.schema_identity: NoArguments,
    PingArguments.schema_identity: PingArguments,
    MissionUnitsArguments.schema_identity: MissionUnitsArguments,
    GeometryArguments.schema_identity: GeometryArguments,
}


def _provider_tool(definition: ToolDefinition) -> dict[str, Any]:
    model = _INPUT_MODELS.get(definition.input_schema)
    if model is None:
        raise YandexPlannerConfigurationError("Unsupported IA-3 tool input schema")
    schema = _strict_provider_schema(model.model_json_schema())
    schema["additionalProperties"] = False
    return {
        "type": "function",
        "name": _provider_tool_name(definition.name),
        "description": definition.description,
        "parameters": schema,
        "strict": True,
    }


def _provider_tool_name(orion_name: str) -> str:
    """Create a stable, collision-safe alias accepted by Yandex function calling."""

    readable = re.sub(r"[^A-Za-z0-9_-]", "_", orion_name)[:50].rstrip("_-")
    digest = hashlib.sha256(orion_name.encode("utf-8")).hexdigest()[:10]
    return f"{readable}_{digest}"


def _strict_provider_schema(value: Any) -> Any:
    """Remove annotation-only keywords and make every function property explicit."""

    if isinstance(value, list):
        return [_strict_provider_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned = {
        key: _strict_provider_schema(item)
        for key, item in value.items()
        if key not in {"title", "default"}
    }
    properties = cleaned.get("properties")
    if cleaned.get("type") == "object" and isinstance(properties, dict):
        cleaned["additionalProperties"] = False
        cleaned["required"] = list(properties)
    return cleaned


def _semantic_format() -> dict[str, Any]:
    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    nullable_scalar = {
        "anyOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "boolean"},
        ]
    }
    source = {
        "type": "object",
        "additionalProperties": False,
        "required": ["context_type", "reference_id"],
        "properties": {
            "context_type": {"type": "string", "const": "tool_result"},
            "reference_id": {"type": "string"},
        },
    }
    nullable_source = {"anyOf": [source, {"type": "null"}]}
    authoritative_fact = {
        "type": "object",
        "additionalProperties": False,
        "required": ["key", "value", "kind", "unit", "source"],
        "properties": {
            "key": {"type": "string"},
            "value": nullable_scalar,
            "kind": {"type": "string", "const": "authoritative"},
            "unit": nullable_string,
            "source": source,
        },
    }
    derived_fact = {
        "type": "object",
        "additionalProperties": False,
        "required": ["key", "value", "kind", "unit", "source"],
        "properties": {
            "key": {"type": "string"},
            "value": nullable_scalar,
            "kind": {"type": "string", "const": "derived"},
            "unit": nullable_string,
            "source": nullable_source,
        },
    }
    issue = {
        "type": "object",
        "additionalProperties": False,
        "required": ["key", "status", "reason", "source"],
        "properties": {
            "key": {"type": "string"},
            "status": {"type": "string", "enum": ["unknown", "unavailable"]},
            "reason": {"type": "string"},
            "source": nullable_source,
        },
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "capability",
            "presentation_mode",
            "authoritative_facts",
            "derived_results",
            "recommendation",
            "assumptions",
            "unavailable_inputs",
            "warnings",
            "verbatim_text",
        ],
        "properties": {
            "capability": nullable_string,
            "presentation_mode": {"type": "string", "const": "naturalize"},
            "authoritative_facts": {"type": "array", "items": authoritative_fact},
            "derived_results": {"type": "array", "items": derived_fact},
            "recommendation": nullable_string,
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "unavailable_inputs": {"type": "array", "items": issue},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "verbatim_text": {"type": "null"},
        },
    }
    return {
        "type": "json_schema",
        "name": "orion_semantic_response",
        "strict": True,
        "schema": schema,
    }


def _instructions(request: PlannerProviderRequest) -> str:
    core = "\n".join(request.core_instructions)
    allowed = ", ".join(str(item) for item in request.allowed_capabilities) or "none"
    return (
        "You are ORION's bounded semantic planner. Use only exposed tools. "
        "Never invent authoritative facts. Every authoritative fact must cite "
        "the completed function call ID as source context_type=tool_result. "
        "Preserve unknown, unavailable, stale and restricted states. Return only "
        "the required structured semantic object; presentation_mode is naturalize. "
        "Select only scalar facts directly needed to answer the user and preserve "
        "each selected WorldFact scalar leaf's exact key, value and unit; do not copy "
        "the whole tool result or its metadata into the response. "
        f"Allowed capabilities: {allowed}.\n{core}"
    )[:8000]


def _safe_tool_result(result: ToolResult) -> dict[str, Any]:
    raw_data = result.data.model_dump(mode="json") if result.data is not None else None
    facts = _compact_world_facts(raw_data)
    return {
        "call_id": result.call_id,
        "tool_name": result.tool_name,
        "tool_version": result.tool_version,
        "status": result.status,
        "data": ({"facts": facts} if facts else raw_data),
        "provenance": (
            result.provenance.model_dump(mode="json") if result.provenance is not None else None
        ),
        "warnings": list(result.warnings),
        "error": result.error.model_dump(mode="json") if result.error is not None else None,
    }


def _compact_world_facts(raw_data: Any) -> list[dict[str, Any]]:
    """Project nested WorldFact values without changing Core's retained ToolResult."""

    projected: list[dict[str, Any]] = []

    def scalar_leaves(prefix: str, value: Any) -> list[tuple[str, Any]]:
        if value is None or isinstance(value, (str, int, float, bool)):
            return [(prefix, value)]
        if isinstance(value, dict):
            leaves: list[tuple[str, Any]] = []
            for key, item in value.items():
                leaves.extend(scalar_leaves(f"{prefix}.{key}", item))
            return leaves
        if isinstance(value, list):
            leaves = []
            for index, item in enumerate(value):
                leaves.extend(scalar_leaves(f"{prefix}.{index}", item))
            return leaves
        return []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            required = {"key", "status", "source", "authority", "value"}
            if required.issubset(value) and all(
                isinstance(value.get(key), str) for key in ("key", "status", "source", "authority")
            ):
                fact_key = cast(str, value["key"])
                leaves = scalar_leaves(fact_key, value.get("value"))
                if not leaves:
                    leaves = [(fact_key, None)]
                for leaf_key, leaf_value in leaves:
                    projected.append(
                        {
                            "key": leaf_key,
                            "value": leaf_value,
                            "status": value.get("status"),
                            "source": value.get("source"),
                            "authority": value.get("authority"),
                            "unit": value.get("unit"),
                            "reason": value.get("reason"),
                            "observed_at": value.get("observed_at"),
                            "age_seconds": value.get("age_seconds"),
                            "generation": value.get("generation"),
                            "confidence": value.get("confidence"),
                        }
                    )
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(raw_data)
    if len(projected) > 512:
        raise YandexPlannerConfigurationError("Tool result fact projection exceeds IA-5 bound")
    if len(json.dumps(projected, ensure_ascii=True, separators=(",", ":"))) > 96_000:
        raise YandexPlannerConfigurationError("Tool result fact projection exceeds IA-5 size bound")
    return projected


def _parse_usage(
    body: Mapping[str, Any],
    model_id: str,
    response_id: str,
    attempts: int,
    latency_ms: float,
) -> PlannerUsage:
    raw = body.get("usage")
    usage = raw if isinstance(raw, dict) else {}
    input_details = usage.get("input_tokens_details")
    cached = input_details.get("cached_tokens") if isinstance(input_details, dict) else None

    def bounded_int(value: Any) -> int | None:
        return value if isinstance(value, int) and 0 <= value <= 100_000_000 else None

    return PlannerUsage(
        model_identifier=model_id,
        provider_request_ids=(cast(str, response_id),),
        input_tokens=bounded_int(usage.get("input_tokens")),
        output_tokens=bounded_int(usage.get("output_tokens")),
        cached_tokens=bounded_int(cached),
        provider_attempts=attempts,
        provider_latency_ms=latency_ms,
    )


def _http_failure(status: int) -> YandexFailureCategory:
    if status == 401:
        return YandexFailureCategory.AUTHENTICATION
    if status == 403:
        return YandexFailureCategory.PERMISSION
    if status == 404:
        return YandexFailureCategory.MODEL_UNAVAILABLE
    if status == 429:
        return YandexFailureCategory.RATE_LIMITED
    if status in {408, 598, 504}:
        return YandexFailureCategory.TIMEOUT
    if status in {500, 502, 503, 599}:
        return YandexFailureCategory.UNAVAILABLE
    return YandexFailureCategory.PROTOCOL


def _safe_provider_id(value: str) -> bool:
    return 1 <= len(value) <= 200 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is not None


async def _read_bounded_json(content: Any) -> Mapping[str, Any] | None:
    """Read every response chunk while enforcing a hard body-size ceiling."""

    body = bytearray()
    async for chunk in content.iter_chunked(64 * 1024):
        body.extend(chunk)
        if len(body) > _MAX_PROVIDER_BODY_BYTES:
            raise YandexPlannerTransportError(YandexFailureCategory.PROTOCOL)
    if not body:
        return None
    try:
        value = json.loads(bytes(body))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


__all__ = [
    "AiohttpYandexResponsesTransport",
    "QWEN_MODEL_ID",
    "QWEN_PROVIDER_ID",
    "YANDEX_RESPONSES_ENDPOINT",
    "YandexFailureCategory",
    "YandexPlannerConfigurationError",
    "YandexPlannerDiagnostic",
    "YandexPlannerDiagnostics",
    "YandexPlannerTransportError",
    "YandexQwenPlannerConfig",
    "YandexQwenPlannerProvider",
    "YandexResponsesTransport",
    "YandexTransportResponse",
    "load_yandex_qwen_planner_config",
]
