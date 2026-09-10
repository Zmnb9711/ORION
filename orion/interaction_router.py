"""IA-6 Core-owned interaction routing and first controlled Planner slice."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID, uuid4

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
from orion.ownship_report import ownship_semantics_from_tool_result
from orion.tool_gateway import ToolGateway
from orion.tool_gateway_contracts import ToolCall, ExecutionContext
from orion.aircraft_interpretation import (
    AircraftAdmission, AircraftInterpreter, AircraftProposal, InterpretationRequest,
    eligible_aircraft_interpretation, source_hash,
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
    BOUNDED_OWNSHIP_REPORT = "bounded_ownship_report"
    PLANNER_CONTROLLED = "planner_controlled"
    UNSUPPORTED = "unsupported"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class RouteReasonCode(StrEnum):
    KNOWN_CORE_HEALTH_INTENT = "known_core_health_intent"
    BOUNDED_OWNSHIP_REPORT = "bounded_ownship_report"
    OWNSHIP_EVIDENCE_REJECTED = "ownship_evidence_rejected"
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
        bounded_ownship_gateway: ToolGateway | None = None,
    ) -> None:
        if max_replay_entries <= 0:
            raise ValueError("Router replay bound must be positive")
        self._planner = planner
        self._provider_factory = provider_factory
        self._clock = clock
        self._bounded_ownship_gateway = bounded_ownship_gateway
        self._replay: OrderedDict[str, tuple[str, InteractionRouterExecution]] = (
            OrderedDict()
        )
        self._max_replay_entries = max_replay_entries
        self._diagnostics: deque[InteractionRouterDiagnostic] = deque(maxlen=500)
        self._lock = RLock()
        self._interpretation_turns: set[UUID] = set()
        self._aircraft_grants: dict[UUID, AircraftAdmission] = {}

    def _interpretation_request(self, identity, text, language, cancellation, provider, budget):
        if not eligible_aircraft_interpretation(text, language) or cancellation.cancelled:
            return None
        with self._lock:
            if identity in self._interpretation_turns or len(self._interpretation_turns) >= 64:
                return None
            self._interpretation_turns.add(identity)
        return InterpretationRequest(interaction_id=identity, operation_id=uuid4(),
            source_text=text, source_sha256=source_hash(text),
            deadline=self._clock() + timedelta(seconds=budget), expected_provider=provider)

    def _admit_interpretation(self, request, proposal, cancellation, emit):
        # Common Core authority for sync development adapter and warm async owner.
        proposal = AircraftProposal.model_validate(proposal.model_dump(), strict=True)
        if (proposal.request != request or proposal.provider_id != request.expected_provider
                or request.source_sha256 != source_hash(request.source_text)):
            raise ValueError("interpretation_source_binding")
        if cancellation.cancelled or self._clock() >= request.deadline:
            raise ValueError("interpretation_cancelled_or_expired")
        emit("proposal", structured_result=proposal.intent.model_dump())
        if proposal.intent.capability != "aircraft.identity":
            emit("admission", status="not_applicable")
            return None
        gateway = self._bounded_ownship_gateway
        if gateway is None or not any(d.name == "orion.world.ownship.get" and d.version == "1.0"
                and d.capability == OWNERSHIP_CAPABILITY for d in gateway.definitions()):
            raise ValueError("interpretation_capability_unavailable")
        grant = AircraftAdmission(request=request, response_id=proposal.response_id)
        with self._lock:
            if cancellation.cancelled or self._clock() >= request.deadline:
                raise ValueError("interpretation_cancelled_or_expired")
            self._aircraft_grants[request.operation_id] = grant
        emit("admission", status="accepted", capability=str(grant.capability))
        return grant

    @staticmethod
    def _interpretation_observer(identity, observe):
        def emit(event, **fields):
            try:
                observe(event, turn_id=str(identity), **fields)
            except Exception:
                pass
        return emit

    def interpret_aircraft(self, *, identity: UUID, text: str, language: str,
                          provider_factory: Callable[[], AircraftInterpreter],
                          cancellation: PlannerCancellationToken,
                          observe: Callable[..., None] = lambda *_a, **_k: None) -> AircraftAdmission | None:
        """Development sync seam; does not change route()/execute()."""
        from orion.aircraft_interpretation import INTERPRETER_PROVIDER, InterpretationCleanupError
        emit = self._interpretation_observer(identity, observe)
        request = self._interpretation_request(identity, text, language, cancellation, INTERPRETER_PROVIDER, 10)
        if request is None:
            return None
        try:
            proposal = provider_factory().interpret(request, cancellation)
            return self._admit_interpretation(request, proposal, cancellation, emit)
        except Exception as exc:
            emit("failed", failure_category=type(exc).__name__, failure_stage="interpretation")
            if isinstance(exc, InterpretationCleanupError):
                raise
            return None

    async def interpret_aircraft_warm(self, utterance, owner, cancellation, *,
                                     observe=lambda *_a, **_k: None):
        """Only an unresolved whole-source turn; never routes or executes tools."""
        from orion.aircraft_interpretation import WARM_INTERPRETER_PROVIDER
        from orion.conversational_contracts import ConversationCleanupError
        started = time.perf_counter()
        emit = self._interpretation_observer(utterance.interaction_id, observe)
        request = self._interpretation_request(utterance.interaction_id, utterance.text,
            utterance.input_language, cancellation, WARM_INTERPRETER_PROVIDER, 1)
        if request is None:
            return None
        try:
            proposal = await owner.interpret(request, cancellation)
            # Provider parse, Core validation and publication share the strict 1s;
            # the owner's independently owned isolation task is NOT awaited here.
            grant = self._admit_interpretation(request, proposal, cancellation, emit)
            emit("core_admission_complete", user_path_ms=(time.perf_counter()-started)*1000,
                 status="accepted" if grant else "not_applicable")
            return grant
        except Exception as exc:
            emit("failed", failure_category=type(exc).__name__, failure_stage="interpretation")
            if isinstance(exc, ConversationCleanupError):
                raise
            return None

    def consume_aircraft_admission(self, grant: AircraftAdmission, identity: UUID,
                                  text: str, cancellation: PlannerCancellationToken) -> bool:
        """Single-use in-process Core authority, not a plausible provider receipt."""
        with self._lock:
            issued = self._aircraft_grants.pop(grant.request.operation_id, None)
            return (issued is grant and not cancellation.cancelled and self._clock() < grant.request.deadline
                    and identity == grant.request.interaction_id and text == grant.request.source_text
                    and source_hash(text) == grant.request.source_sha256)

    def route(
        self,
        request: InteractionRequest,
        communication: CommunicationContext,
    ) -> InteractionRoutingDecision:
        normalized = _normalize_text(request.text)
        reference = _communication_reference(communication)
        if self._bounded_ownship_gateway is not None:
            # Explicit recovery field mode, not a change to the default IA-6
            # policy. Match the whole authorized query, never keyword presence.
            matched = bool(re.fullmatch(
                r"\s*какой\s+мой\s+текущий\s+курс\s+и\s+координаты[?.!]?\s*",
                request.text.casefold(),
            )) and communication.domain is CommunicationDomain.NAVIGATION
            return InteractionRoutingDecision(
                interaction_id=request.interaction_id,
                route=InteractionRoute.BOUNDED_OWNSHIP_REPORT if matched else InteractionRoute.UNSUPPORTED,
                reason_code=RouteReasonCode.BOUNDED_OWNSHIP_REPORT if matched else RouteReasonCode.UNSUPPORTED_INTERACTION_CLASS,
                domain=communication.domain,
                requested_capability=OWNERSHIP_CAPABILITY if matched else None,
                planner_required=False, policy_version="recovery.ownship-route.v1",
                communication_context_reference=reference,
            )
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

            if decision.route is InteractionRoute.BOUNDED_OWNSHIP_REPORT:
                assert self._bounded_ownship_gateway is not None
                try:
                    tool = self._bounded_ownship_gateway.execute(ToolCall(
                        call_id=f"ownship-{request.interaction_id}",
                        name="orion.world.ownship.get", version="1.0",
                        context=ExecutionContext(
                            actor_id="orion-interaction-router",
                            interaction_id=str(request.interaction_id),
                            session_id=request.session_id, turn_id=request.turn_id,
                            role="pilot", domain="navigation",
                            allowed_capabilities=(OWNERSHIP_CAPABILITY,),
                            permissions=("world.read",), deadline=deadline,
                        ),
                    ))
                    if cancellation.cancelled:
                        return self._remember(replay_key, signature, self._terminal_error(
                            request, communication, InteractionRoute.DENIED,
                            RouteReasonCode.CANCELLED, RouterExecutionStatus.CANCELLED,
                        ))
                    if self._now() >= deadline:
                        return self._remember(replay_key, signature, self._terminal_error(
                            request, communication, InteractionRoute.UNAVAILABLE,
                            RouteReasonCode.DEADLINE_EXCEEDED, RouterExecutionStatus.TIMED_OUT,
                        ))
                    response = ownship_semantics_from_tool_result(tool, request.interaction_id, now=self._now())
                    result = InteractionRouterExecution(
                        decision=decision, status=RouterExecutionStatus.COMPLETED,
                        response=response,
                    )
                except Exception:
                    # Safe category only: no raw ToolResult/provider data in speech.
                    result = InteractionRouterExecution(
                        decision=decision, status=RouterExecutionStatus.FAILED,
                        error_code=RouteReasonCode.OWNSHIP_EVIDENCE_REJECTED,
                    )
                self._record(decision, RouterDiagnosticStage.COMPLETED if result.response else RouterDiagnosticStage.REJECTED)
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
                        "Return only ownship.heading_deg, ownship.position.latitude, and "
                        "ownship.position.longitude; do not return altitude or any other WorldFact.",
                        "Put each requested known authoritative leaf in authoritative_facts with "
                        "its exact key, value, unit, authority, and completed call ID; if heading "
                        "or position is unavailable or unknown, use only the matching sourced "
                        "unavailable_inputs entry.",
                        "This request requires no calculation: derived_results must be empty, and "
                        "no fact key may appear in more than one semantic section.",
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
