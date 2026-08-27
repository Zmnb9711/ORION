"""IA-6 Core-owned interaction routing and first controlled Planner slice."""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from orion.communication_contracts import CommunicationContext, CommunicationDomain
from orion.interaction_contracts import (
    CapabilityId,
    ContextReference,
    InteractionRequest,
    SemanticResponse,
)
from orion.planner import (
    PlannerCancellationToken,
    PlannerProvider,
    PlannerTaskRunner,
    planner_runner,
)
from orion.planner_contracts import (
    PlannerErrorCode,
    PlannerExecutionPolicy,
    PlannerTaskSnapshot,
    PlannerTaskStatus,
    ProviderRetryPolicy,
)

POLICY_VERSION = "ia6.router-policy.v1"
OWNERSHIP_CAPABILITY = CapabilityId("world.ownship.read")
HEALTH_CAPABILITY = CapabilityId("test.ping")

PolicyVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    ),
]


class _RouterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class InteractionRoute(StrEnum):
    DIRECT_HEALTH_OR_TEST = "direct_health_or_test"
    PLANNER_CONTROLLED = "planner_controlled"
    UNSUPPORTED = "unsupported"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class RouteReasonCode(StrEnum):
    KNOWN_CORE_HEALTH_INTENT = "known_core_health_intent"
    CURRENT_OWNSHIP_SITUATION_REQUIRES_PLANNER = (
        "current_ownship_situation_requires_planner"
    )
    UNSUPPORTED_INTERACTION_CLASS = "unsupported_interaction_class"
    REPLAY_CONFLICT = "replay_conflict"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
    PLANNER_CONFIGURATION_UNAVAILABLE = "planner_configuration_unavailable"
    PLANNER_FAILED = "planner_failed"


class RouterExecutionStatus(StrEnum):
    COMPLETED = "completed"
    UNSUPPORTED = "unsupported"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class InteractionRoutingDecision(_RouterModel):
    interaction_id: UUID
    route: InteractionRoute
    reason_code: RouteReasonCode
    domain: CommunicationDomain
    requested_capability: CapabilityId | None = None
    planner_required: bool
    policy_version: PolicyVersion = POLICY_VERSION
    communication_context_reference: ContextReference | None = None

    @model_validator(mode="after")
    def validate_route(self) -> Self:
        if self.route is InteractionRoute.PLANNER_CONTROLLED:
            if not self.planner_required or self.requested_capability is None:
                raise ValueError("Planner route requires one Core-selected capability")
        elif self.planner_required:
            raise ValueError("Only planner route may require Planner")
        return self


class InteractionRouterExecution(_RouterModel):
    schema_version: Literal["ia6.router-result.v1"] = "ia6.router-result.v1"
    decision: InteractionRoutingDecision
    status: RouterExecutionStatus
    response: SemanticResponse | None = Field(default=None, repr=False)
    planner_task: PlannerTaskSnapshot | None = None
    error_code: RouteReasonCode | PlannerErrorCode | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status is RouterExecutionStatus.COMPLETED:
            if self.response is None or self.error_code is not None:
                raise ValueError(
                    "Completed router result requires response and no error"
                )
        elif self.response is not None or self.error_code is None:
            raise ValueError(
                "Unsuccessful router result requires error and no response"
            )
        return self


class RouterDiagnosticStage(StrEnum):
    DECIDED = "decided"
    REPLAYED = "replayed"
    COMPLETED = "completed"
    REJECTED = "rejected"


class InteractionRouterDiagnostic(_RouterModel):
    stage: RouterDiagnosticStage
    timestamp: datetime
    interaction_id: UUID
    route: InteractionRoute
    reason_code: RouteReasonCode
    domain: CommunicationDomain
    capability: CapabilityId | None = None
    policy_version: PolicyVersion = POLICY_VERSION

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Router diagnostic timestamp must be timezone-aware")
        return value


class ProviderFactory(Protocol):
    def __call__(self) -> PlannerProvider: ...


class InteractionRouter:
    """Bounded Core policy: semantic route first, presentation context separately."""

    def __init__(
        self,
        *,
        planner: PlannerTaskRunner = planner_runner,
        provider_factory: ProviderFactory,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_replay_entries: int = 256,
    ) -> None:
        if max_replay_entries <= 0:
            raise ValueError("Router replay bound must be positive")
        self._planner = planner
        self._provider_factory = provider_factory
        self._clock = clock
        self._replay: OrderedDict[str, tuple[str, InteractionRouterExecution]] = (
            OrderedDict()
        )
        self._max_replay_entries = max_replay_entries
        self._diagnostics: deque[InteractionRouterDiagnostic] = deque(maxlen=500)
        self._lock = RLock()

    def route(
        self,
        request: InteractionRequest,
        communication: CommunicationContext,
    ) -> InteractionRoutingDecision:
        normalized = _normalize_text(request.text)
        reference = _communication_reference(communication)
        if normalized in _HEALTH_INTENTS:
            return InteractionRoutingDecision(
                interaction_id=request.interaction_id,
                route=InteractionRoute.DIRECT_HEALTH_OR_TEST,
                reason_code=RouteReasonCode.KNOWN_CORE_HEALTH_INTENT,
                domain=communication.domain,
                requested_capability=HEALTH_CAPABILITY,
                planner_required=False,
                communication_context_reference=reference,
            )
        if _is_current_ownship_query(normalized):
            return InteractionRoutingDecision(
                interaction_id=request.interaction_id,
                route=InteractionRoute.PLANNER_CONTROLLED,
                reason_code=RouteReasonCode.CURRENT_OWNSHIP_SITUATION_REQUIRES_PLANNER,
                domain=communication.domain,
                requested_capability=OWNERSHIP_CAPABILITY,
                planner_required=True,
                communication_context_reference=reference,
            )
        return InteractionRoutingDecision(
            interaction_id=request.interaction_id,
            route=InteractionRoute.UNSUPPORTED,
            reason_code=RouteReasonCode.UNSUPPORTED_INTERACTION_CLASS,
            domain=communication.domain,
            planner_required=False,
            communication_context_reference=reference,
        )

    def execute(
        self,
        request: InteractionRequest,
        communication: CommunicationContext,
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken | None = None,
    ) -> InteractionRouterExecution:
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            raise ValueError("Router deadline must be timezone-aware")
        cancellation = cancellation or PlannerCancellationToken()
        signature = _request_signature(request, communication)
        replay_key = str(request.interaction_id)
        with self._lock:
            replayed = self._replay.get(replay_key)
            if replayed is not None:
                if replayed[0] == signature:
                    self._record(replayed[1].decision, RouterDiagnosticStage.REPLAYED)
                    return replayed[1]
                return self._terminal_error(
                    request,
                    communication,
                    InteractionRoute.DENIED,
                    RouteReasonCode.REPLAY_CONFLICT,
                    RouterExecutionStatus.DENIED,
                )

            if cancellation.cancelled:
                return self._remember(
                    replay_key,
                    signature,
                    self._terminal_error(
                        request,
                        communication,
                        InteractionRoute.DENIED,
                        RouteReasonCode.CANCELLED,
                        RouterExecutionStatus.CANCELLED,
                    ),
                )
            if self._now() >= deadline:
                return self._remember(
                    replay_key,
                    signature,
                    self._terminal_error(
                        request,
                        communication,
                        InteractionRoute.UNAVAILABLE,
                        RouteReasonCode.DEADLINE_EXCEEDED,
                        RouterExecutionStatus.TIMED_OUT,
                    ),
                )

            decision = self.route(request, communication)
            self._record(decision, RouterDiagnosticStage.DECIDED)
            if decision.route is InteractionRoute.UNSUPPORTED:
                result = InteractionRouterExecution(
                    decision=decision,
                    status=RouterExecutionStatus.UNSUPPORTED,
                    error_code=RouteReasonCode.UNSUPPORTED_INTERACTION_CLASS,
                )
                self._record(decision, RouterDiagnosticStage.REJECTED)
                return self._remember(replay_key, signature, result)
            if decision.route is InteractionRoute.DIRECT_HEALTH_OR_TEST:
                response = SemanticResponse(
                    interaction_id=request.interaction_id,
                    capability=HEALTH_CAPABILITY,
                    recommendation="ORION Core health check passed.",
                )
                result = InteractionRouterExecution(
                    decision=decision,
                    status=RouterExecutionStatus.COMPLETED,
                    response=response,
                )
                self._record(decision, RouterDiagnosticStage.COMPLETED)
                return self._remember(replay_key, signature, result)

            try:
                provider = self._provider_factory()
            except Exception:
                result = InteractionRouterExecution(
                    decision=decision.model_copy(
                        update={
                            "route": InteractionRoute.UNAVAILABLE,
                            "reason_code": RouteReasonCode.PLANNER_CONFIGURATION_UNAVAILABLE,
                            "planner_required": False,
                        }
                    ),
                    status=RouterExecutionStatus.UNAVAILABLE,
                    error_code=RouteReasonCode.PLANNER_CONFIGURATION_UNAVAILABLE,
                )
                self._record(result.decision, RouterDiagnosticStage.REJECTED)
                return self._remember(replay_key, signature, result)

            controlled_request = request.model_copy(
                update={
                    "allowed_capabilities": (OWNERSHIP_CAPABILITY,),
                    "domain_hint": communication.domain.value,
                }
            )
            planner_result = self._planner.execute(
                controlled_request,
                provider,
                PlannerExecutionPolicy(
                    actor_id="orion-interaction-router",
                    provider_id=provider.provider_id,
                    permissions=("world.read",),
                    core_instructions=(
                        "For the controlled ownship situation request, call the exposed ownship tool.",
                        "Return only exact scalar WorldFact keys, values and units from that result.",
                        "Never upgrade observed, derived, stale or unavailable data to authoritative.",
                    ),
                    deadline=deadline,
                    max_tool_rounds=1,
                    provider_retry=ProviderRetryPolicy(max_attempts=2),
                ),
                cancellation=cancellation,
            )
            if planner_result.response is not None:
                if not _valid_ownship_slice_response(planner_result.response):
                    result = InteractionRouterExecution(
                        decision=decision,
                        status=RouterExecutionStatus.FAILED,
                        planner_task=planner_result.task,
                        error_code=PlannerErrorCode.INVALID_FINAL_RESPONSE,
                    )
                    self._record(decision, RouterDiagnosticStage.REJECTED)
                    return self._remember(replay_key, signature, result)
                result = InteractionRouterExecution(
                    decision=decision,
                    status=RouterExecutionStatus.COMPLETED,
                    response=planner_result.response,
                    planner_task=planner_result.task,
                )
                self._record(decision, RouterDiagnosticStage.COMPLETED)
                return self._remember(replay_key, signature, result)

            status = {
                PlannerTaskStatus.CANCELLED: RouterExecutionStatus.CANCELLED,
                PlannerTaskStatus.TIMED_OUT: RouterExecutionStatus.TIMED_OUT,
            }.get(planner_result.task.status, RouterExecutionStatus.FAILED)
            result = InteractionRouterExecution(
                decision=decision,
                status=status,
                planner_task=planner_result.task,
                error_code=(
                    planner_result.error.code
                    if planner_result.error is not None
                    else RouteReasonCode.PLANNER_FAILED
                ),
            )
            self._record(decision, RouterDiagnosticStage.REJECTED)
            return self._remember(replay_key, signature, result)

    def diagnostic_snapshot(self) -> tuple[InteractionRouterDiagnostic, ...]:
        with self._lock:
            return tuple(self._diagnostics)

    def _terminal_error(
        self,
        request: InteractionRequest,
        communication: CommunicationContext,
        route: InteractionRoute,
        reason: RouteReasonCode,
        status: RouterExecutionStatus,
    ) -> InteractionRouterExecution:
        decision = InteractionRoutingDecision(
            interaction_id=request.interaction_id,
            route=route,
            reason_code=reason,
            domain=communication.domain,
            planner_required=False,
            communication_context_reference=_communication_reference(communication),
        )
        self._record(decision, RouterDiagnosticStage.REJECTED)
        return InteractionRouterExecution(
            decision=decision,
            status=status,
            error_code=reason,
        )

    def _remember(
        self,
        key: str,
        signature: str,
        result: InteractionRouterExecution,
    ) -> InteractionRouterExecution:
        self._replay[key] = (signature, result)
        self._replay.move_to_end(key)
        while len(self._replay) > self._max_replay_entries:
            self._replay.popitem(last=False)
        return result

    def _record(
        self,
        decision: InteractionRoutingDecision,
        stage: RouterDiagnosticStage,
    ) -> None:
        self._diagnostics.append(
            InteractionRouterDiagnostic(
                stage=stage,
                timestamp=self._now(),
                interaction_id=decision.interaction_id,
                route=decision.route,
                reason_code=decision.reason_code,
                domain=decision.domain,
                capability=decision.requested_capability,
            )
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Router clock must return timezone-aware timestamps")
        return value


_HEALTH_INTENTS = {
    "ping",
    "health check",
    "test connection",
    "core health check",
    "проверка ядра",
    "проверка связи с ядром",
}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", text.casefold())).strip()


def _is_current_ownship_query(text: str) -> bool:
    has_heading = "heading" in text or "курс" in text
    has_position = any(
        marker in text
        for marker in (
            "position",
            "coordinates",
            "location",
            "where am i",
            "позици",
            "координат",
            "где я",
        )
    )
    return has_heading and has_position


def _valid_ownship_slice_response(response: SemanticResponse) -> bool:
    """Require complete heading plus two-coordinate position semantics."""

    if response.capability != OWNERSHIP_CAPABILITY:
        return False
    fact_keys = {fact.key for fact in response.authoritative_facts}
    unavailable_keys = {
        issue.key
        for issue in response.unavailable_inputs
        if issue.source is not None and issue.source.context_type == "tool_result"
    }
    heading_complete = (
        "ownship.heading_deg" in fact_keys or "ownship.heading_deg" in unavailable_keys
    )
    position_complete = {
        "ownship.position.latitude",
        "ownship.position.longitude",
    }.issubset(fact_keys) or "ownship.position" in unavailable_keys
    allowed_fact_keys = {
        "ownship.heading_deg",
        "ownship.position.latitude",
        "ownship.position.longitude",
    }
    return (
        heading_complete and position_complete and fact_keys.issubset(allowed_fact_keys)
    )


def _communication_reference(context: CommunicationContext) -> ContextReference:
    return ContextReference(
        context_type="communication_context",
        reference_id=f"{context.profile_id.value}:{context.domain.value}",
    )


def _request_signature(
    request: InteractionRequest,
    communication: CommunicationContext,
) -> str:
    payload = {
        "request": request.model_dump(mode="json"),
        "communication": communication.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "InteractionRoute",
    "InteractionRouter",
    "InteractionRouterDiagnostic",
    "InteractionRouterExecution",
    "InteractionRoutingDecision",
    "RouteReasonCode",
    "RouterExecutionStatus",
]
