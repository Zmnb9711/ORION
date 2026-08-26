"""IA-4 Core-owned planner lifecycle and provider-neutral tool loop."""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, RLock
from typing import Protocol, cast
from uuid import uuid4

from orion.interaction_contracts import ContextReference, InteractionRequest, SemanticResponse
from orion.planner_contracts import (
    PlannerCancelledEvent,
    PlannerDiagnosticEvent,
    PlannerDiagnosticStage,
    PlannerError,
    PlannerErrorCategory,
    PlannerErrorCode,
    PlannerEvent,
    PlannerExecutionPolicy,
    PlannerExecutionResult,
    PlannerFailedEvent,
    PlannerFinalResponseEvent,
    PlannerProviderRequest,
    PlannerStartedEvent,
    PlannerTaskSnapshot,
    PlannerTaskStatus,
    PlannerTimedOutEvent,
    PlannerToolCallsEvent,
    PlannerToolRequest,
    PlannerUsage,
    ProviderIdentifier,
)
from orion.tool_gateway import ToolGateway, tool_gateway
from orion.tool_gateway_contracts import (
    ExecutionContext,
    ToolCall,
    ToolReceipt,
    ToolResult,
    ToolResultStatus,
)
from orion.world_model_contracts import WorldFactAuthority


logger = logging.getLogger(__name__)


class PlannerRun(Protocol):
    """Short-lived provider continuation for exactly one Core planner task."""

    def next_event(
        self,
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken,
    ) -> PlannerEvent: ...

    def continue_with_tool_results(self, results: tuple[ToolResult, ...]) -> None: ...

    def cancel(self) -> None: ...


class PlannerProvider(Protocol):
    """Provider adapter boundary implemented later by IA-5."""

    provider_id: ProviderIdentifier

    def start(self, request: PlannerProviderRequest) -> PlannerRun: ...


class PlannerCancellationToken:
    """Thread-safe Core signal; it carries no provider-specific lifecycle state."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Allow adapters to wait for cancellation without busy polling."""

        return self._event.wait(timeout)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class PlannerTaskStateMachine:
    """Small explicit state machine; it is deliberately not a workflow engine."""

    _ALLOWED = {
        PlannerTaskStatus.CREATED: {
            PlannerTaskStatus.RUNNING,
            PlannerTaskStatus.FAILED,
            PlannerTaskStatus.CANCELLED,
            PlannerTaskStatus.TIMED_OUT,
        },
        PlannerTaskStatus.RUNNING: {
            PlannerTaskStatus.WAITING_FOR_TOOLS,
            PlannerTaskStatus.COMPLETED,
            PlannerTaskStatus.FAILED,
            PlannerTaskStatus.CANCELLED,
            PlannerTaskStatus.TIMED_OUT,
        },
        PlannerTaskStatus.WAITING_FOR_TOOLS: {
            PlannerTaskStatus.RUNNING,
            PlannerTaskStatus.FAILED,
            PlannerTaskStatus.CANCELLED,
            PlannerTaskStatus.TIMED_OUT,
        },
        PlannerTaskStatus.COMPLETED: set(),
        PlannerTaskStatus.FAILED: set(),
        PlannerTaskStatus.CANCELLED: set(),
        PlannerTaskStatus.TIMED_OUT: set(),
    }

    def __init__(self) -> None:
        self._status = PlannerTaskStatus.CREATED

    @property
    def status(self) -> PlannerTaskStatus:
        return self._status

    def transition(self, target: PlannerTaskStatus) -> None:
        if target not in self._ALLOWED[self._status]:
            raise ValueError(f"Illegal planner transition: {self._status.value} -> {target.value}")
        self._status = target


class PlannerDiagnostics:
    """Bounded scalar lifecycle evidence; prompts, events and results are excluded."""

    def __init__(self, max_events: int = 500) -> None:
        if max_events <= 0:
            raise ValueError("Planner diagnostics max_events must be positive")
        self._events: deque[PlannerDiagnosticEvent] = deque(maxlen=max_events)
        self._lock = RLock()

    def record(self, event: PlannerDiagnosticEvent) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> tuple[PlannerDiagnosticEvent, ...]:
        with self._lock:
            return tuple(self._events)


class PlannerTaskRunner:
    """Execute one bounded provider run while Core retains policy and tool authority."""

    _EVENT_TYPES = (
        PlannerStartedEvent,
        PlannerToolCallsEvent,
        PlannerFinalResponseEvent,
        PlannerFailedEvent,
        PlannerCancelledEvent,
        PlannerTimedOutEvent,
    )

    def __init__(
        self,
        *,
        gateway: ToolGateway = tool_gateway,
        diagnostics: PlannerDiagnostics | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.perf_counter,
        task_id_factory: Callable[[], str] = lambda: f"planner-{uuid4()}",
    ) -> None:
        self._gateway = gateway
        self._diagnostics = diagnostics or PlannerDiagnostics()
        self._clock = clock
        self._monotonic = monotonic
        self._task_id_factory = task_id_factory

    def diagnostic_snapshot(self) -> tuple[PlannerDiagnosticEvent, ...]:
        return self._diagnostics.snapshot()

    def execute(
        self,
        request: InteractionRequest,
        provider: PlannerProvider,
        policy: PlannerExecutionPolicy,
        *,
        cancellation: PlannerCancellationToken | None = None,
    ) -> PlannerExecutionResult:
        task_id = self._task_id_factory()
        created_at = self._now()
        started = self._monotonic()
        state = PlannerTaskStateMachine()
        cancellation = cancellation or PlannerCancellationToken()
        requested_call_ids: list[str] = []
        completed_receipts: list[ToolReceipt] = []
        ledger: dict[str, tuple[str, ToolResult]] = {}
        event_ledger: dict[str, str] = {}
        tool_rounds = 0
        usage: PlannerUsage | None = None
        run: PlannerRun | None = None

        self._diagnostic(
            PlannerDiagnosticStage.TASK_CREATED,
            task_id,
            request,
            policy.provider_id,
            created_at,
        )

        def finish_error(error: PlannerError, target: PlannerTaskStatus) -> PlannerExecutionResult:
            if state.status is not target:
                state.transition(target)
            completed_at = self._now()
            stage = {
                PlannerTaskStatus.CANCELLED: PlannerDiagnosticStage.CANCELLED,
                PlannerTaskStatus.TIMED_OUT: PlannerDiagnosticStage.TIMED_OUT,
            }.get(target, PlannerDiagnosticStage.FAILED)
            self._diagnostic(
                stage,
                task_id,
                request,
                policy.provider_id,
                completed_at,
                decision=error.code,
                latency_ms=self._latency(started),
            )
            snapshot = self._snapshot(
                task_id=task_id,
                request=request,
                policy=policy,
                state=state,
                created_at=created_at,
                completed_at=completed_at,
                tool_rounds=tool_rounds,
                requested_call_ids=requested_call_ids,
                completed_receipts=completed_receipts,
                response=None,
                error=error,
                usage=usage,
                started=started,
            )
            return PlannerExecutionResult(task=snapshot, error=error)

        if provider.provider_id != policy.provider_id:
            return finish_error(
                self._error(PlannerErrorCode.PROVIDER_PROTOCOL_ERROR),
                PlannerTaskStatus.FAILED,
            )
        if cancellation.cancelled:
            return finish_error(self._error(PlannerErrorCode.CANCELLED), PlannerTaskStatus.CANCELLED)
        if created_at >= policy.deadline:
            return finish_error(
                self._error(PlannerErrorCode.DEADLINE_EXCEEDED),
                PlannerTaskStatus.TIMED_OUT,
            )

        available_tools = tuple(
            definition
            for definition in self._gateway.definitions()
            if definition.capability in request.allowed_capabilities
        )
        provider_request = PlannerProviderRequest(
            planner_task_id=task_id,
            interaction=request,
            allowed_capabilities=request.allowed_capabilities,
            available_tools=available_tools,
            core_instructions=policy.core_instructions,
            deadline=policy.deadline,
            retry_policy=policy.provider_retry,
        )
        state.transition(PlannerTaskStatus.RUNNING)
        try:
            run = provider.start(provider_request)
        except Exception:
            logger.error("IA-4 provider start failed safely: %s", policy.provider_id)
            return finish_error(
                self._error(PlannerErrorCode.INTERNAL_PLANNER_ERROR),
                PlannerTaskStatus.FAILED,
            )
        self._diagnostic(
            PlannerDiagnosticStage.PROVIDER_STARTED,
            task_id,
            request,
            policy.provider_id,
            self._now(),
            decision="accepted",
        )

        while True:
            if cancellation.cancelled:
                self._cancel_run(run)
                return finish_error(self._error(PlannerErrorCode.CANCELLED), PlannerTaskStatus.CANCELLED)
            if self._now() >= policy.deadline:
                self._cancel_run(run)
                return finish_error(
                    self._error(PlannerErrorCode.DEADLINE_EXCEEDED),
                    PlannerTaskStatus.TIMED_OUT,
                )
            try:
                raw_event = run.next_event(
                    deadline=policy.deadline,
                    cancellation=cancellation,
                )
            except Exception:
                logger.error("IA-4 provider event failed safely: %s", policy.provider_id)
                return finish_error(
                    self._error(PlannerErrorCode.INTERNAL_PLANNER_ERROR),
                    PlannerTaskStatus.FAILED,
                )
            if cancellation.cancelled:
                self._cancel_run(run)
                return finish_error(self._error(PlannerErrorCode.CANCELLED), PlannerTaskStatus.CANCELLED)
            if self._now() >= policy.deadline:
                self._cancel_run(run)
                return finish_error(
                    self._error(PlannerErrorCode.DEADLINE_EXCEEDED),
                    PlannerTaskStatus.TIMED_OUT,
                )
            if not isinstance(raw_event, self._EVENT_TYPES):
                return finish_error(
                    self._error(PlannerErrorCode.INVALID_PROVIDER_EVENT),
                    PlannerTaskStatus.FAILED,
                )
            event = cast(PlannerEvent, raw_event)
            event_signature = self._event_signature(event)
            previous_event_signature = event_ledger.get(event.event_id)
            replayed_event = previous_event_signature is not None
            if replayed_event and previous_event_signature != event_signature:
                return finish_error(
                    self._error(PlannerErrorCode.INVALID_PROVIDER_EVENT),
                    PlannerTaskStatus.FAILED,
                )
            event_ledger[event.event_id] = event_signature
            usage = self._merge_usage(usage, event.usage)

            if isinstance(event, PlannerStartedEvent):
                continue
            if isinstance(event, PlannerFailedEvent):
                return finish_error(self._error(event.error.code), PlannerTaskStatus.FAILED)
            if isinstance(event, PlannerCancelledEvent):
                return finish_error(
                    self._error(PlannerErrorCode.CANCELLED),
                    PlannerTaskStatus.CANCELLED,
                )
            if isinstance(event, PlannerTimedOutEvent):
                return finish_error(
                    self._error(PlannerErrorCode.PROVIDER_TIMEOUT),
                    PlannerTaskStatus.FAILED,
                )
            if isinstance(event, PlannerFinalResponseEvent):
                if not self._valid_final_response(event.response, request, ledger):
                    return finish_error(
                        self._error(PlannerErrorCode.INVALID_FINAL_RESPONSE),
                        PlannerTaskStatus.FAILED,
                    )
                state.transition(PlannerTaskStatus.COMPLETED)
                completed_at = self._now()
                self._diagnostic(
                    PlannerDiagnosticStage.COMPLETED,
                    task_id,
                    request,
                    policy.provider_id,
                    completed_at,
                    event_id=event.event_id,
                    decision="completed",
                    latency_ms=self._latency(started),
                )
                snapshot = self._snapshot(
                    task_id=task_id,
                    request=request,
                    policy=policy,
                    state=state,
                    created_at=created_at,
                    completed_at=completed_at,
                    tool_rounds=tool_rounds,
                    requested_call_ids=requested_call_ids,
                    completed_receipts=completed_receipts,
                    response=event.response,
                    error=None,
                    usage=usage,
                    started=started,
                )
                return PlannerExecutionResult(task=snapshot, response=event.response)

            if not isinstance(event, PlannerToolCallsEvent):
                return finish_error(
                    self._error(PlannerErrorCode.INVALID_PROVIDER_EVENT),
                    PlannerTaskStatus.FAILED,
                )
            if not replayed_event:
                if tool_rounds >= policy.max_tool_rounds:
                    return finish_error(
                        self._error(PlannerErrorCode.TOOL_ROUND_LIMIT_EXCEEDED),
                        PlannerTaskStatus.FAILED,
                    )
                tool_rounds += 1
            state.transition(PlannerTaskStatus.WAITING_FOR_TOOLS)
            results: list[ToolResult] = []
            for tool_request in event.calls:
                signature = self._tool_signature(tool_request)
                previous = ledger.get(tool_request.call_id)
                if previous is not None:
                    previous_signature, previous_result = previous
                    if previous_signature != signature:
                        return finish_error(
                            self._error(PlannerErrorCode.INVALID_TOOL_REQUEST),
                            PlannerTaskStatus.FAILED,
                        )
                    results.append(previous_result)
                    continue
                if cancellation.cancelled:
                    self._cancel_run(run)
                    return finish_error(
                        self._error(PlannerErrorCode.CANCELLED),
                        PlannerTaskStatus.CANCELLED,
                    )
                if self._now() >= policy.deadline:
                    self._cancel_run(run)
                    return finish_error(
                        self._error(PlannerErrorCode.DEADLINE_EXCEEDED),
                        PlannerTaskStatus.TIMED_OUT,
                    )
                self._diagnostic(
                    PlannerDiagnosticStage.TOOL_REQUESTED,
                    task_id,
                    request,
                    policy.provider_id,
                    self._now(),
                    event_id=event.event_id,
                    call_id=tool_request.call_id,
                    tool_name=tool_request.name,
                    decision="accepted",
                )
                try:
                    result = self._execute_tool(task_id, request, policy, tool_request)
                except Exception:
                    logger.error("IA-4 Tool Gateway call failed safely: %s", tool_request.name)
                    return finish_error(
                        self._error(PlannerErrorCode.INTERNAL_PLANNER_ERROR),
                        PlannerTaskStatus.FAILED,
                    )
                ledger[tool_request.call_id] = (signature, result)
                requested_call_ids.append(tool_request.call_id)
                completed_receipts.append(result.receipt)
                results.append(result)
                self._diagnostic(
                    PlannerDiagnosticStage.TOOL_RESULT,
                    task_id,
                    request,
                    policy.provider_id,
                    self._now(),
                    event_id=event.event_id,
                    call_id=tool_request.call_id,
                    tool_name=tool_request.name,
                    decision=(
                        "completed"
                        if result.status is ToolResultStatus.COMPLETED
                        else PlannerErrorCode.TOOL_CALL_REJECTED
                    ),
                )
                if result.status is not ToolResultStatus.COMPLETED:
                    return finish_error(
                        self._error(PlannerErrorCode.TOOL_CALL_REJECTED),
                        PlannerTaskStatus.FAILED,
                    )
            if cancellation.cancelled:
                self._cancel_run(run)
                return finish_error(self._error(PlannerErrorCode.CANCELLED), PlannerTaskStatus.CANCELLED)
            if self._now() >= policy.deadline:
                self._cancel_run(run)
                return finish_error(
                    self._error(PlannerErrorCode.DEADLINE_EXCEEDED),
                    PlannerTaskStatus.TIMED_OUT,
                )
            state.transition(PlannerTaskStatus.RUNNING)
            try:
                run.continue_with_tool_results(tuple(results))
            except Exception:
                logger.error("IA-4 provider continuation failed safely: %s", policy.provider_id)
                return finish_error(
                    self._error(PlannerErrorCode.INTERNAL_PLANNER_ERROR),
                    PlannerTaskStatus.FAILED,
                )
            self._diagnostic(
                PlannerDiagnosticStage.CONTINUATION_STARTED,
                task_id,
                request,
                policy.provider_id,
                self._now(),
                event_id=event.event_id,
                decision="accepted",
            )

    def _execute_tool(
        self,
        task_id: str,
        request: InteractionRequest,
        policy: PlannerExecutionPolicy,
        tool_request: PlannerToolRequest,
    ) -> ToolResult:
        context = ExecutionContext(
            actor_id=policy.actor_id,
            interaction_id=str(request.interaction_id),
            session_id=request.session_id,
            turn_id=request.turn_id,
            task_id=task_id,
            provider_id=policy.provider_id,
            role=request.role_hint,
            domain=request.domain_hint,
            allowed_capabilities=request.allowed_capabilities,
            permissions=policy.permissions,
            deadline=policy.deadline,
        )
        return self._gateway.execute(
            ToolCall(
                call_id=tool_request.call_id,
                name=tool_request.name,
                version=tool_request.version,
                arguments=tool_request.arguments,
                context=context,
                idempotency_key=tool_request.idempotency_key,
            )
        )

    @staticmethod
    def _valid_final_response(
        response: SemanticResponse,
        request: InteractionRequest,
        ledger: dict[str, tuple[str, ToolResult]],
    ) -> bool:
        if response.interaction_id != request.interaction_id:
            return False
        if response.capability is not None and response.capability not in request.allowed_capabilities:
            return False
        for fact in response.authoritative_facts:
            source: ContextReference | None = fact.source
            if source is None or source.context_type != "tool_result":
                return False
            recorded = ledger.get(source.reference_id)
            if recorded is None:
                return False
            result = recorded[1]
            if result.status is not ToolResultStatus.COMPLETED or result.provenance is None:
                return False
            if WorldFactAuthority.AUTHORITATIVE not in result.provenance.authorities:
                return False
        return True

    @staticmethod
    def _tool_signature(request: PlannerToolRequest) -> str:
        payload = request.model_dump(mode="json", exclude={"call_id"})
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _event_signature(event: PlannerEvent) -> str:
        payload = event.model_dump(mode="json", exclude={"event_id"})
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _merge_usage(current: PlannerUsage | None, update: PlannerUsage | None) -> PlannerUsage | None:
        if update is None:
            return current
        if current is None:
            return update
        request_ids = tuple(dict.fromkeys((*current.provider_request_ids, *update.provider_request_ids)))
        payload = current.model_dump()
        for key, value in update.model_dump().items():
            if value is not None and key != "provider_request_ids":
                payload[key] = value
        payload["provider_request_ids"] = request_ids
        return PlannerUsage.model_validate(payload)

    @staticmethod
    def _error(code: PlannerErrorCode) -> PlannerError:
        categories = {
            PlannerErrorCode.PROVIDER_UNAVAILABLE: PlannerErrorCategory.PROVIDER,
            PlannerErrorCode.PROVIDER_TIMEOUT: PlannerErrorCategory.PROVIDER,
            PlannerErrorCode.PROVIDER_PROTOCOL_ERROR: PlannerErrorCategory.PROTOCOL,
            PlannerErrorCode.INVALID_PROVIDER_EVENT: PlannerErrorCategory.PROTOCOL,
            PlannerErrorCode.INVALID_TOOL_REQUEST: PlannerErrorCategory.TOOL,
            PlannerErrorCode.TOOL_CALL_REJECTED: PlannerErrorCategory.TOOL,
            PlannerErrorCode.TOOL_ROUND_LIMIT_EXCEEDED: PlannerErrorCategory.TOOL,
            PlannerErrorCode.INVALID_FINAL_RESPONSE: PlannerErrorCategory.VALIDATION,
            PlannerErrorCode.DEADLINE_EXCEEDED: PlannerErrorCategory.LIFECYCLE,
            PlannerErrorCode.CANCELLED: PlannerErrorCategory.LIFECYCLE,
            PlannerErrorCode.INTERNAL_PLANNER_ERROR: PlannerErrorCategory.INTERNAL,
        }
        messages = {
            PlannerErrorCode.PROVIDER_UNAVAILABLE: "Planner provider is unavailable.",
            PlannerErrorCode.PROVIDER_TIMEOUT: "Planner provider timed out.",
            PlannerErrorCode.PROVIDER_PROTOCOL_ERROR: "Planner provider protocol is incompatible.",
            PlannerErrorCode.INVALID_PROVIDER_EVENT: "Planner provider returned an invalid event.",
            PlannerErrorCode.INVALID_TOOL_REQUEST: "Planner requested an invalid or conflicting tool call.",
            PlannerErrorCode.TOOL_CALL_REJECTED: "Core rejected the requested tool call.",
            PlannerErrorCode.TOOL_ROUND_LIMIT_EXCEEDED: "Planner tool-round limit was exceeded.",
            PlannerErrorCode.INVALID_FINAL_RESPONSE: "Planner final response failed Core validation.",
            PlannerErrorCode.DEADLINE_EXCEEDED: "Core planner deadline was exceeded.",
            PlannerErrorCode.CANCELLED: "Core cancelled the planner task.",
            PlannerErrorCode.INTERNAL_PLANNER_ERROR: "Planner execution failed safely.",
        }
        return PlannerError(
            code=code,
            category=categories[code],
            message=messages[code],
            retryable=code in {
                PlannerErrorCode.PROVIDER_UNAVAILABLE,
                PlannerErrorCode.PROVIDER_TIMEOUT,
            },
        )

    def _snapshot(
        self,
        *,
        task_id: str,
        request: InteractionRequest,
        policy: PlannerExecutionPolicy,
        state: PlannerTaskStateMachine,
        created_at: datetime,
        completed_at: datetime,
        tool_rounds: int,
        requested_call_ids: list[str],
        completed_receipts: list[ToolReceipt],
        response: SemanticResponse | None,
        error: PlannerError | None,
        usage: PlannerUsage | None,
        started: float,
    ) -> PlannerTaskSnapshot:
        return PlannerTaskSnapshot(
            planner_task_id=task_id,
            interaction_id=request.interaction_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider_id=policy.provider_id,
            allowed_capabilities=request.allowed_capabilities,
            status=state.status,
            created_at=created_at,
            deadline=policy.deadline,
            completed_at=completed_at,
            tool_rounds=tool_rounds,
            requested_call_ids=tuple(requested_call_ids),
            completed_tool_receipts=tuple(completed_receipts),
            final_response_id=response.response_id if response is not None else None,
            error=error,
            usage=usage,
            total_latency_ms=self._latency(started),
        )

    def _diagnostic(
        self,
        stage: PlannerDiagnosticStage,
        task_id: str,
        request: InteractionRequest,
        provider_id: str,
        timestamp: datetime,
        *,
        event_id: str | None = None,
        call_id: str | None = None,
        tool_name: str | None = None,
        decision: PlannerErrorCode | str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        self._diagnostics.record(
            PlannerDiagnosticEvent(
                stage=stage,
                timestamp=timestamp,
                planner_task_id=task_id,
                interaction_id=request.interaction_id,
                provider_id=provider_id,
                event_id=event_id,
                call_id=call_id,
                tool_name=tool_name,
                decision=decision,  # type: ignore[arg-type]
                latency_ms=latency_ms,
            )
        )

    @staticmethod
    def _cancel_run(run: PlannerRun | None) -> None:
        if run is None:
            return
        try:
            run.cancel()
        except Exception:
            logger.error("IA-4 provider cancellation failed safely")

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Planner clock must return timezone-aware timestamps")
        return now

    def _latency(self, started: float) -> float:
        return round(max(0.0, (self._monotonic() - started) * 1000), 3)


planner_runner = PlannerTaskRunner()
