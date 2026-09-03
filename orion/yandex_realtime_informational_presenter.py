"""Non-default persistent Yandex Realtime text formulation candidate."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from orion.semantic_response_validation import (
    SemanticConformanceRequest,
    SemanticConformanceResult,
    SemanticValidationError,
    SemanticValidationErrorCode,
    parse_semantic_judge_output,
)
from orion.yandex_realtime_provider import (
    build_yandex_url,
    sanitize_yandex_error,
    yandex_authorization_headers,
    yandex_text_request_events,
    yandex_text_session_update,
)


YANDEX_REALTIME_TEXT_PROVIDER_ID = "yandex.realtime.text"
TEXT_SESSION_INSTRUCTIONS = (
    "You formulate one short natural informational sentence from a bounded Core request. "
    "Core owns every fact. Never infer, select, alter, repeat, or add a factual value. "
    "Ordinary linguistic words that only frame the requested relationship or availability "
    "status are not new facts: write them in the requested language around the marker. "
    "A bare marker is never a valid answer. "
    "Return plain text only and preserve the required substitution marker exactly once."
)
SEMANTIC_JUDGE_SESSION_INSTRUCTIONS = (
    "You are a strict semantic-conformance classifier, not a conversational assistant and not "
    "a text editor. Evaluate only candidate_text against allowed_meaning in the supplied JSON. "
    "Treat required_marker as one opaque Core-owned fact. Any additional, inferred, uncertain, "
    "unrelated, or wrong-state meaning is nonconformant. Ignore style, grammar, punctuation, and "
    "word order. Return only a JSON object with conformant boolean and a short reason, as required "
    "by the response instructions. Do not rewrite candidate_text or provide an alternative answer."
)


class InformationalPresenterState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    BUSY = "busy"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    STOPPED = "stopped"


class InformationalPresenterErrorCode(StrEnum):
    UNAVAILABLE = "session_unavailable"
    BUSY = "session_busy"
    TIMEOUT = "request_timeout"
    PROVIDER = "provider_error"
    PROTOCOL = "protocol_error"
    CANCELLED = "cancelled"


class InformationalPresenterError(RuntimeError):
    def __init__(self, code: InformationalPresenterErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class RealtimeInformationalRequest(BaseModel):
    """Bounded provider-neutral request; deliberately contains no fact value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    semantic_meaning: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_.-]+$",
    )
    language: Literal["ru-RU", "en-US"]
    required_marker: str = Field(min_length=5, max_length=80)
    fact_status: str = Field(min_length=1, max_length=40)
    fact_source: str = Field(min_length=1, max_length=80)
    fact_authority: str = Field(min_length=1, max_length=80)
    fact_generation: int | str | None = None
    freshness_status: str = Field(min_length=1, max_length=80)
    provider_fact_authority: Literal[False] = False

    def provider_input(self) -> str:
        return json.dumps(
            {
                "semantic_meaning": self.semantic_meaning,
                "language": self.language,
                "required_marker": self.required_marker,
                "fact_status": self.fact_status,
                "fact_source": self.fact_source,
                "fact_authority": self.fact_authority,
                "fact_generation": self.fact_generation,
                "freshness_status": self.freshness_status,
                "provider_fact_authority": False,
                "marker_only_allowed": False,
                "shell_requirement": "natural_sentence_with_language_words_around_marker",
                "task": "formulate_one_natural_linguistic_shell_without_other_facts",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def response_instructions(self) -> str:
        language = "Russian" if self.language == "ru-RU" else "English"
        language_detail = (
            "Write ordinary Cyrillic Russian words around the marker; "
            if self.language == "ru-RU"
            else "Write ordinary English words around the marker; "
        )
        status_detail = (
            "Express only that the authoritative aircraft information is unavailable. "
            if self.fact_status == "unavailable"
            else "Express only the current-aircraft identity relationship. "
        )
        return (
            f"Return exactly one concise natural {language} sentence as plain text. "
            f"Use the exact marker {self.required_marker} exactly once. "
            f"{language_detail}the marker alone is not a sentence and is invalid. "
            f"{status_detail}"
            "Do not write any aircraft identifier or factual value. "
            "Do not add a second claim, explanation, heading, JSON, or Markdown."
        )


class RealtimeInformationalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    provider_id: Literal["yandex.realtime.text"] = YANDEX_REALTIME_TEXT_PROVIDER_ID
    provider_response_id: str
    provider_item_id: str | None = None
    output_text: str = Field(min_length=1, max_length=1_000)
    first_token_latency_ms: float = Field(ge=0)
    complete_latency_ms: float = Field(ge=0)
    session_reused: bool
    provider_fact_authority: Literal[False] = False


@dataclass(slots=True, frozen=True)
class YandexRealtimeTextConfig:
    api_key: str = field(repr=False)
    folder_id: str
    connect_timeout_s: float = 10.0
    request_timeout_s: float = 8.0
    reconnect_delay_s: float = 0.25


@dataclass(slots=True, frozen=True)
class _RealtimeTextOperationResult:
    provider_response_id: str
    provider_item_id: str | None
    output_text: str
    first_token_latency_ms: float
    complete_latency_ms: float
    session_reused: bool


class RealtimeTextTransport(Protocol):
    async def connect(self) -> None: ...

    async def send_json(self, payload: dict[str, object]) -> None: ...

    async def receive_json(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class AiohttpRealtimeTextTransport:
    """Thin transport reusing the canonical Yandex URL/auth protocol helpers."""

    def __init__(self, config: YandexRealtimeTextConfig) -> None:
        self._config = config
        self._session: Any = None
        self._websocket: Any = None

    async def connect(self) -> None:
        import aiohttp

        timeout = aiohttp.ClientTimeout(
            total=self._config.connect_timeout_s,
            connect=self._config.connect_timeout_s,
        )
        self._session = aiohttp.ClientSession(timeout=timeout)
        try:
            self._websocket = await self._session.ws_connect(
                build_yandex_url(self._config.folder_id),
                headers=yandex_authorization_headers(self._config.api_key),
                heartbeat=20.0,
                autoclose=True,
            )
        except Exception:
            await self.close()
            raise

    async def send_json(self, payload: dict[str, object]) -> None:
        if self._websocket is None:
            raise ConnectionError("Yandex Realtime text transport is not connected")
        await self._websocket.send_json(payload)

    async def receive_json(self) -> dict[str, Any]:
        import aiohttp

        if self._websocket is None:
            raise ConnectionError("Yandex Realtime text transport is not connected")
        message = await self._websocket.receive()
        if message.type is aiohttp.WSMsgType.TEXT:
            value = message.json()
            if not isinstance(value, dict):
                raise ValueError("Yandex Realtime event is not an object")
            return value
        if message.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.CLOSING,
        }:
            raise ConnectionError("Yandex Realtime text session closed")
        if message.type is aiohttp.WSMsgType.ERROR:
            raise ConnectionError("Yandex Realtime text transport failed")
        raise ValueError("Yandex Realtime returned an unsupported frame")

    async def close(self) -> None:
        if self._websocket is not None and not self._websocket.closed:
            await self._websocket.close(code=1000)
        self._websocket = None
        if self._session is not None:
            await self._session.close()
        self._session = None


TransportFactory = Callable[[YandexRealtimeTextConfig], RealtimeTextTransport]


class BoundedPresenterDiagnostics:
    """Scalar-only bounded diagnostics; never stores prompts, responses, or secrets."""

    def __init__(self, max_events: int = 1_000) -> None:
        if max_events <= 0:
            raise ValueError("Diagnostic bound must be positive")
        self._events: deque[dict[str, object]] = deque(maxlen=max_events)
        self._lock = threading.RLock()

    def record(self, event: str, **metadata: object) -> None:
        safe: dict[str, object] = {"event": event[:100]}
        for key, value in metadata.items():
            if value is None or isinstance(value, (bool, int, float)):
                safe[key[:80]] = value
            elif isinstance(value, str):
                safe[key[:80]] = value[:200]
            else:
                raise TypeError("Presenter diagnostics accept scalar metadata only")
        with self._lock:
            self._events.append(safe)

    def snapshot(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(dict(item) for item in self._events)


class RealtimeTextResponseAssembler:
    """One-generation response correlator independent of transport and lifecycle."""

    def __init__(
        self,
        *,
        generation: int,
        request_id: str,
        started: float,
        record: Callable[..., None],
    ) -> None:
        self.generation = generation
        self.request_id = request_id
        self.started = started
        self.record = record
        self.response_id: str | None = None
        self.provider_item_id: str | None = None
        self.first_token_at: float | None = None
        self.text_done_at: float | None = None
        self.terminal_at: float | None = None
        self.status: str | None = None
        self._deltas: list[str] = []
        self._done_text: str | None = None
        self._invalidated = False

    def invalidate(self) -> None:
        self._invalidated = True

    @property
    def completed(self) -> bool:
        return (
            not self._invalidated
            and self._done_text is not None
            and self.status == "completed"
            and self.terminal_at is not None
        )

    @property
    def output_text(self) -> str:
        if not self.completed or self._done_text is None:
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.PROTOCOL,
                "Yandex Realtime text response is incomplete",
            )
        return self._done_text

    def _matches(self, event: dict[str, Any]) -> bool:
        response = event.get("response")
        nested_id = response.get("id") if isinstance(response, dict) else None
        event_id = event.get("response_id") or nested_id
        return (
            self.response_id is not None
            and isinstance(event_id, str)
            and event_id == self.response_id
        )

    def handle(self, event: dict[str, Any], *, generation: int) -> None:
        kind = str(event.get("type") or "")
        if self._invalidated or generation != self.generation:
            self.record(
                "formulation_late_response_ignored",
                correlation_id=self.request_id,
                provider_event_type=kind,
                generation=generation,
            )
            return
        now = time.perf_counter()
        if kind == "conversation.item.created":
            item = event.get("item")
            if isinstance(item, dict):
                value = item.get("id")
                if isinstance(value, str):
                    self.provider_item_id = value[:200]
            return
        if kind == "response.created":
            response = event.get("response")
            value = response.get("id") if isinstance(response, dict) else event.get("response_id")
            if not isinstance(value, str) or not value:
                raise InformationalPresenterError(
                    InformationalPresenterErrorCode.PROTOCOL,
                    "Yandex Realtime response.created omitted response identity",
                )
            if self.response_id is None:
                self.response_id = value
            elif value != self.response_id:
                self.record(
                    "formulation_late_response_ignored",
                    correlation_id=self.request_id,
                    provider_event_type=kind,
                    generation=generation,
                )
            return
        if kind == "response.output_text.delta":
            if not self._matches(event):
                self.record(
                    "formulation_late_response_ignored",
                    correlation_id=self.request_id,
                    provider_event_type=kind,
                    generation=generation,
                )
                return
            delta = event.get("delta")
            if not isinstance(delta, str):
                raise InformationalPresenterError(
                    InformationalPresenterErrorCode.PROTOCOL,
                    "Yandex Realtime text delta is invalid",
                )
            if delta:
                self._deltas.append(delta)
                if self.first_token_at is None:
                    self.first_token_at = now
                    self.record(
                        "formulation_first_token",
                        correlation_id=self.request_id,
                        provider=YANDEX_REALTIME_TEXT_PROVIDER_ID,
                        latency_ms=round((now - self.started) * 1000, 3),
                    )
            return
        if kind == "response.output_text.done":
            if not self._matches(event):
                self.record(
                    "formulation_late_response_ignored",
                    correlation_id=self.request_id,
                    provider_event_type=kind,
                    generation=generation,
                )
                return
            value = event.get("text")
            if not isinstance(value, str) or not value.strip():
                raise InformationalPresenterError(
                    InformationalPresenterErrorCode.PROTOCOL,
                    "Yandex Realtime complete text is missing",
                )
            if self._done_text is not None:
                self.record(
                    "formulation_late_response_ignored",
                    correlation_id=self.request_id,
                    provider_event_type="duplicate_text_done",
                    generation=generation,
                )
                return
            assembled = "".join(self._deltas)
            if assembled and " ".join(assembled.split()) != " ".join(value.split()):
                raise InformationalPresenterError(
                    InformationalPresenterErrorCode.PROTOCOL,
                    "Yandex Realtime text delta/final mismatch",
                )
            self._done_text = value.strip()
            self.text_done_at = now
            if self.first_token_at is None:
                self.first_token_at = now
                self.record(
                    "formulation_first_token",
                    correlation_id=self.request_id,
                    provider=YANDEX_REALTIME_TEXT_PROVIDER_ID,
                    latency_ms=round((now - self.started) * 1000, 3),
                )
            return
        if kind == "response.done":
            if not self._matches(event):
                self.record(
                    "formulation_late_response_ignored",
                    correlation_id=self.request_id,
                    provider_event_type=kind,
                    generation=generation,
                )
                return
            if self.terminal_at is not None:
                self.record(
                    "formulation_late_response_ignored",
                    correlation_id=self.request_id,
                    provider_event_type="duplicate_response_done",
                    generation=generation,
                )
                return
            response = event.get("response")
            self.status = str(response.get("status") or "") if isinstance(response, dict) else ""
            self.terminal_at = now
            if self.status != "completed":
                raise InformationalPresenterError(
                    InformationalPresenterErrorCode.PROVIDER,
                    "Yandex Realtime text response did not complete successfully",
                )
            return
        if kind == "error":
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.PROVIDER,
                "Yandex Realtime rejected the text formulation request",
            )


class YandexRealtimeInformationalPresenter:
    """One explicit, warm, non-default text presenter with no audio ownership."""

    provider_id = YANDEX_REALTIME_TEXT_PROVIDER_ID

    def __init__(
        self,
        config: YandexRealtimeTextConfig,
        *,
        transport_factory: TransportFactory = AiohttpRealtimeTextTransport,
        diagnostics: BoundedPresenterDiagnostics | None = None,
    ) -> None:
        self._config = config
        self._transport_factory = transport_factory
        self._diagnostics = diagnostics or BoundedPresenterDiagnostics()
        self._transport: RealtimeTextTransport | None = None
        self._state = InformationalPresenterState.DISCONNECTED
        self._generation = 0
        self._completed_requests = 0
        self._session_id: str | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        self._reconnect_task: asyncio.Task[None] | None = None
        self._stopped = False

    @property
    def state(self) -> InformationalPresenterState:
        return self._state

    @property
    def queue_maxsize(self) -> int:
        return self._queue.maxsize

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def diagnostic_snapshot(self) -> tuple[dict[str, object], ...]:
        return self._diagnostics.snapshot()

    def record_event(self, event: str, **metadata: object) -> None:
        self._diagnostics.record(event, **metadata)

    async def connect(self) -> bool:
        """Connect explicitly; return True only when an existing session was reused."""

        if self._state is InformationalPresenterState.READY:
            return True
        if self._stopped or self._state is InformationalPresenterState.STOPPED:
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.UNAVAILABLE,
                "Yandex Realtime text presenter is stopped",
            )
        if self._state not in {
            InformationalPresenterState.DISCONNECTED,
            InformationalPresenterState.FAILED,
            InformationalPresenterState.RECONNECTING,
        }:
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.BUSY,
                "Yandex Realtime text presenter cannot connect in its current state",
            )
        self._state = InformationalPresenterState.CONNECTING
        self.record_event(
            "formulation_session_connect_started",
            provider=self.provider_id,
        )
        transport = self._transport_factory(self._config)
        try:
            await asyncio.wait_for(transport.connect(), self._config.connect_timeout_s)
            await transport.send_json(
                yandex_text_session_update(instructions=TEXT_SESSION_INSTRUCTIONS)
            )
            while True:
                event = await asyncio.wait_for(
                    transport.receive_json(),
                    self._config.connect_timeout_s,
                )
                kind = str(event.get("type") or "")
                if kind == "session.updated":
                    session = event.get("session")
                    if isinstance(session, dict) and isinstance(session.get("id"), str):
                        self._session_id = str(session["id"])[:200]
                    break
                if kind == "error":
                    raise InformationalPresenterError(
                        InformationalPresenterErrorCode.PROVIDER,
                        "Yandex rejected the text-only session configuration",
                    )
        except Exception as exc:
            await transport.close()
            self._state = InformationalPresenterState.FAILED
            self.record_event(
                "formulation_failed",
                provider=self.provider_id,
                stage="connect",
                error_type=type(exc).__name__,
            )
            if isinstance(exc, InformationalPresenterError):
                raise
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.UNAVAILABLE,
                sanitize_yandex_error(type(exc).__name__, self._config.api_key),
            ) from exc
        self._transport = transport
        self._state = InformationalPresenterState.READY
        self.record_event(
            "formulation_session_ready",
            provider=self.provider_id,
            session_id=self._session_id or "not_reported",
        )
        return False

    async def formulate(
        self,
        request: RealtimeInformationalRequest,
    ) -> RealtimeInformationalResult:
        self.record_event(
            "formulation_provider_selected",
            correlation_id=request.request_id,
            provider=self.provider_id,
            backend="yandex_realtime_text",
            provider_fact_authority=False,
        )
        self.record_event(
            "formulation_request_started",
            correlation_id=request.request_id,
            provider=self.provider_id,
            language=request.language,
            semantic_meaning=request.semantic_meaning,
            fact_source=request.fact_source,
            fact_authority=request.fact_authority,
            fact_generation=str(request.fact_generation or "unknown"),
            freshness_status=request.freshness_status,
            session_reused=self._completed_requests > 0,
        )
        result = await self._run_text_operation(
            request_id=request.request_id,
            input_text=request.provider_input(),
            instructions=request.response_instructions(),
            event_id_kind="info",
            failure_event="formulation_failed",
        )
        self.record_event(
            "formulation_completed",
            correlation_id=request.request_id,
            provider=self.provider_id,
            provider_response_id=result.provider_response_id,
            latency_ms=round(result.complete_latency_ms, 3),
            session_reused=result.session_reused,
        )
        return RealtimeInformationalResult(
            request_id=request.request_id,
            provider_response_id=result.provider_response_id,
            provider_item_id=result.provider_item_id,
            output_text=result.output_text,
            first_token_latency_ms=result.first_token_latency_ms,
            complete_latency_ms=result.complete_latency_ms,
            session_reused=result.session_reused,
        )

    async def evaluate_semantic_conformance(
        self,
        request: SemanticConformanceRequest,
    ) -> SemanticConformanceResult:
        """Run one fail-closed semantic judge operation on this same warm session."""

        self.record_event(
            "semantic_validation_started",
            correlation_id=request.request_id,
            provider=self.provider_id,
            semantic_meaning=request.policy.semantic_meaning,
            fact_state=request.fact_state,
            session_reused=self._completed_requests > 0,
            provider_fact_authority=False,
        )
        try:
            result = await self._run_text_operation(
                request_id=request.request_id,
                input_text=request.provider_input(),
                instructions=request.response_instructions(),
                event_id_kind="semantic",
                failure_event="semantic_validation_failed",
                temporary_session_instructions=SEMANTIC_JUDGE_SESSION_INSTRUCTIONS,
            )
            decision = parse_semantic_judge_output(
                result.output_text,
                request=request,
                provider_id=self.provider_id,
                provider_response_id=result.provider_response_id,
                latency_ms=result.complete_latency_ms,
                session_reused=result.session_reused,
            )
        except SemanticValidationError:
            self.record_event(
                "semantic_validation_failed",
                correlation_id=request.request_id,
                provider=self.provider_id,
                error_type=SemanticValidationErrorCode.JUDGE_PROTOCOL.value,
            )
            raise
        self.record_event(
            "semantic_validation_completed",
            correlation_id=request.request_id,
            provider=self.provider_id,
            provider_response_id=decision.provider_response_id,
            verdict=decision.verdict.value,
            unsupported_category_count=len(decision.unsupported_categories),
            latency_ms=round(decision.latency_ms, 3),
            session_reused=decision.session_reused,
            provider_fact_authority=False,
        )
        return decision

    async def _run_text_operation(
        self,
        *,
        request_id: str,
        input_text: str,
        instructions: str,
        event_id_kind: str,
        failure_event: str,
        temporary_session_instructions: str | None = None,
    ) -> _RealtimeTextOperationResult:
        if self._state is InformationalPresenterState.BUSY or self._queue.full():
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.BUSY,
                "Yandex Realtime text presenter is busy",
            )
        if self._state is not InformationalPresenterState.READY or self._transport is None:
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.UNAVAILABLE,
                "Yandex Realtime text presenter is not ready",
            )
        self._queue.put_nowait(request_id)
        self._queue.get_nowait()
        self._state = InformationalPresenterState.BUSY
        self._generation += 1
        generation = self._generation
        started = time.perf_counter()
        assembler = RealtimeTextResponseAssembler(
            generation=generation,
            request_id=request_id,
            started=started,
            record=self.record_event,
        )
        session_reused = self._completed_requests > 0
        try:
            result = await asyncio.wait_for(
                self._execute_text_operation_with_session_mode(
                    request_id=request_id,
                    input_text=input_text,
                    instructions=instructions,
                    event_id_kind=event_id_kind,
                    assembler=assembler,
                    session_reused=session_reused,
                    temporary_session_instructions=temporary_session_instructions,
                ),
                self._config.request_timeout_s,
            )
        except asyncio.TimeoutError as exc:
            assembler.invalidate()
            await self._cancel_response(assembler.response_id, request_id)
            self.record_event(
                failure_event,
                correlation_id=request_id,
                provider=self.provider_id,
                error_type=InformationalPresenterErrorCode.TIMEOUT.value,
            )
            await self._invalidate_connection(schedule_reconnect=True)
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.TIMEOUT,
                "Yandex Realtime text formulation timed out",
            ) from exc
        except asyncio.CancelledError:
            assembler.invalidate()
            await self._cancel_response(assembler.response_id, request_id)
            await self._invalidate_connection(schedule_reconnect=True)
            raise
        except InformationalPresenterError as exc:
            assembler.invalidate()
            self.record_event(
                failure_event,
                correlation_id=request_id,
                provider=self.provider_id,
                error_type=exc.code.value,
            )
            await self._invalidate_connection(schedule_reconnect=True)
            raise
        finally:
            self._queue.task_done()
        self._completed_requests += 1
        self._state = InformationalPresenterState.READY
        return result

    async def _execute_text_operation_with_session_mode(
        self,
        *,
        request_id: str,
        input_text: str,
        instructions: str,
        event_id_kind: str,
        assembler: RealtimeTextResponseAssembler,
        session_reused: bool,
        temporary_session_instructions: str | None,
    ) -> _RealtimeTextOperationResult:
        session_mode_changed = temporary_session_instructions is not None
        if session_mode_changed:
            await self._update_session_instructions(temporary_session_instructions)
        try:
            result = await self._execute_text_operation(
                request_id=request_id,
                input_text=input_text,
                instructions=instructions,
                event_id_kind=event_id_kind,
                assembler=assembler,
                session_reused=session_reused,
            )
        except BaseException:
            if session_mode_changed:
                try:
                    await self._update_session_instructions(TEXT_SESSION_INSTRUCTIONS)
                except Exception:
                    pass
            raise
        if session_mode_changed:
            await self._update_session_instructions(TEXT_SESSION_INSTRUCTIONS)
        return result

    async def _update_session_instructions(self, instructions: str) -> None:
        """Switch the operation contract on the existing session and await confirmation."""

        if self._transport is None:
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.UNAVAILABLE,
                "Yandex Realtime text presenter is not ready",
            )
        await self._transport.send_json(yandex_text_session_update(instructions=instructions))
        while True:
            event = await self._transport.receive_json()
            kind = str(event.get("type") or "")
            if kind == "session.updated":
                return
            if kind == "error":
                raise InformationalPresenterError(
                    InformationalPresenterErrorCode.PROVIDER,
                    "Yandex rejected the text-session operation contract",
                )
            raise InformationalPresenterError(
                InformationalPresenterErrorCode.PROTOCOL,
                "Yandex returned an unexpected event while updating the text session",
            )

    async def _execute_text_operation(
        self,
        *,
        request_id: str,
        input_text: str,
        instructions: str,
        event_id_kind: str,
        assembler: RealtimeTextResponseAssembler,
        session_reused: bool,
    ) -> _RealtimeTextOperationResult:
        assert self._transport is not None
        item_event_id = f"orion-{event_id_kind}-item-{request_id}"
        response_event_id = f"orion-{event_id_kind}-response-{request_id}"
        item, create = yandex_text_request_events(
            input_text=input_text,
            instructions=instructions,
            item_event_id=item_event_id,
            response_event_id=response_event_id,
        )
        await self._transport.send_json(item)
        await self._transport.send_json(create)
        while not assembler.completed:
            event = await self._transport.receive_json()
            assembler.handle(event, generation=assembler.generation)
        completed = time.perf_counter()
        assert assembler.response_id is not None
        first_token_at = assembler.first_token_at or completed
        return _RealtimeTextOperationResult(
            provider_response_id=assembler.response_id,
            provider_item_id=assembler.provider_item_id,
            output_text=assembler.output_text,
            first_token_latency_ms=(first_token_at - assembler.started) * 1000,
            complete_latency_ms=(completed - assembler.started) * 1000,
            session_reused=session_reused,
        )

    async def _cancel_response(self, response_id: str | None, request_id: str) -> None:
        if self._transport is None:
            return
        self.record_event(
            "formulation_cancel_requested",
            correlation_id=request_id,
            provider=self.provider_id,
            provider_response_id=response_id or "unknown",
        )
        if response_id:
            try:
                await self._transport.send_json(
                    {
                        "type": "response.cancel",
                        "event_id": f"orion-info-cancel-{request_id}",
                        "response_id": response_id,
                    }
                )
            except Exception:
                pass

    async def _invalidate_connection(self, *, schedule_reconnect: bool) -> None:
        transport = self._transport
        self._transport = None
        self._session_id = None
        if transport is not None:
            await transport.close()
        self.record_event(
            "formulation_session_disconnected",
            provider=self.provider_id,
        )
        if schedule_reconnect and not self._stopped:
            self._state = InformationalPresenterState.RECONNECTING
            self.record_event(
                "formulation_session_reconnect_scheduled",
                provider=self.provider_id,
                delay_ms=round(self._config.reconnect_delay_s * 1000, 3),
            )
            self._reconnect_task = asyncio.create_task(self._reconnect())
        else:
            self._state = InformationalPresenterState.DISCONNECTED

    async def _reconnect(self) -> None:
        await asyncio.sleep(self._config.reconnect_delay_s)
        if self._stopped:
            return
        self._state = InformationalPresenterState.DISCONNECTED
        try:
            await self.connect()
        except InformationalPresenterError:
            self._state = InformationalPresenterState.FAILED

    async def close(self) -> None:
        self._stopped = True
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        transport = self._transport
        self._transport = None
        if transport is not None:
            await transport.close()
        self._state = InformationalPresenterState.STOPPED
        self.record_event(
            "formulation_session_disconnected",
            provider=self.provider_id,
            stopped=True,
        )


__all__ = [
    "AiohttpRealtimeTextTransport",
    "BoundedPresenterDiagnostics",
    "InformationalPresenterError",
    "InformationalPresenterErrorCode",
    "InformationalPresenterState",
    "RealtimeInformationalRequest",
    "RealtimeInformationalResult",
    "RealtimeTextResponseAssembler",
    "SEMANTIC_JUDGE_SESSION_INSTRUCTIONS",
    "TEXT_SESSION_INSTRUCTIONS",
    "YANDEX_REALTIME_TEXT_PROVIDER_ID",
    "YandexRealtimeInformationalPresenter",
    "YandexRealtimeTextConfig",
]
