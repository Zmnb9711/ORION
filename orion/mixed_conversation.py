"""Provider-neutral FREE + OPERATIONAL decomposition and local composition."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from orion.atc_core import AtcSessionIdentity
from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
    ResponseCompositionPlan,
    UntrustedConversationalEnvelope,
)
from orion.golden_takeoff_vertical import (
    GoldenTakeoffResult,
    GoldenTakeoffVertical,
    TakeoffIntent,
    TakeoffIntentKind,
    TakeoffIntentStatus,
)
from orion.interaction_contracts import CapabilityId, InteractionRequest
from orion.planner import PlannerCancellationToken, PlannerProvider
from orion.planner_contracts import (
    PlannerError,
    PlannerFailedEvent,
    PlannerProviderRequest,
    PlannerToolCallsEvent,
    PlannerUsage,
    ProviderRetryPolicy,
)
from orion.tool_gateway_contracts import (
    ToolAccessMode,
    ToolDefinition,
    ToolLatencyClass,
    ToolPolicy,
    ToolSchemaModel,
)


MIXED_DECOMPOSITION_CAPABILITY = CapabilityId("conversation.mixed.decompose")
MIXED_DECOMPOSITION_TOOL_NAME = "orion.conversation.mixed_decomposition.emit"


class MixedDecompositionStatus(StrEnum):
    CLASSIFIED = "classified"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class FreeSemanticKind(StrEnum):
    GREETING = "greeting"
    SOCIAL_EXCHANGE = "social_exchange"


class MixedOperationalIntent(StrEnum):
    TAKEOFF_CLEARANCE_REQUEST = "takeoff_clearance_request"


class MixedConversationDecomposition(ToolSchemaModel):
    """Strict provider result; it contains intent, never an ATC decision."""

    schema_identity = "orion.mixed-conversation-decomposition.v1"
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    detected_input_language: str = Field(pattern=r"^(?:ru-RU|en-US|unknown)$")
    status: MixedDecompositionStatus
    free_semantics: tuple[FreeSemanticKind, ...] = Field(max_length=2)
    free_source_text: str | None = Field(default=None, min_length=1, max_length=500)
    free_response_text: str | None = Field(default=None, min_length=1, max_length=240)
    operational_intents: tuple[MixedOperationalIntent, ...] = Field(max_length=1)
    ambiguity_reason: str | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_decomposition_shape(self) -> Self:
        if len(self.free_semantics) != len(set(self.free_semantics)):
            raise ValueError("FREE semantic kinds must be unique")
        if len(self.operational_intents) != len(set(self.operational_intents)):
            raise ValueError("operational intents must be unique")
        has_free = bool(self.free_semantics)
        if has_free != (
            self.free_source_text is not None and self.free_response_text is not None
        ):
            raise ValueError("FREE semantics require both source and response text")
        if self.status is MixedDecompositionStatus.CLASSIFIED:
            if not has_free and not self.operational_intents:
                raise ValueError("classified decomposition requires FREE or OPERATIONAL content")
            if self.ambiguity_reason is not None:
                raise ValueError("classified decomposition cannot contain ambiguity")
        elif self.status is MixedDecompositionStatus.AMBIGUOUS:
            if self.operational_intents or self.ambiguity_reason is None:
                raise ValueError("ambiguous decomposition cannot assert operational intent")
        elif self.operational_intents or self.ambiguity_reason is not None:
            raise ValueError("unsupported decomposition cannot assert intent or ambiguity")
        if self.free_response_text is not None and _contains_operational_decision(
            self.free_response_text
        ):
            raise ValueError("FREE response attempts to contain an operational decision")
        return self


class MixedProviderStatus(StrEnum):
    COMPLETED = "completed"
    PROVIDER_FAILED = "provider_failed"
    INVALID_OUTPUT = "invalid_output"


class MixedProviderResult(ToolSchemaModel):
    schema_identity = "orion.mixed-conversation-provider-result.v1"
    status: MixedProviderStatus
    decomposition: MixedConversationDecomposition | None = None
    usage: PlannerUsage | None = None
    error: PlannerError | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        completed = self.status is MixedProviderStatus.COMPLETED
        if completed != (self.decomposition is not None):
            raise ValueError("only completed provider result has decomposition")
        if completed == (self.error is not None):
            raise ValueError("provider error shape is invalid")
        return self


class MixedCompositionOutcome(ToolSchemaModel):
    schema_identity = "orion.mixed-conversation-composition.v1"
    decomposition: MixedConversationDecomposition
    golden_result: GoldenTakeoffResult | None = Field(default=None, repr=False)
    plan: ResponseCompositionPlan | None = Field(default=None, repr=False)
    final_text: str | None = Field(default=None, min_length=1, max_length=4_000)


def mixed_decomposition_tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name=MIXED_DECOMPOSITION_TOOL_NAME,
        version="1.0",
        capability=MIXED_DECOMPOSITION_CAPABILITY,
        description=(
            "Emit one strict bounded decomposition of FREE social content and the "
            "optional takeoff-clearance request intent; never decide clearance."
        ),
        input_schema=MixedConversationDecomposition.schema_identity,
        output_schema=MixedProviderResult.schema_identity,
        access=ToolAccessMode.READ,
        latency_class=ToolLatencyClass.EXTERNAL_OR_LONG,
        policy=ToolPolicy(),
    )


def request_mixed_decomposition(
    provider: PlannerProvider,
    *,
    utterance: str,
    interaction_id: UUID,
    planner_task_id: str,
    deadline: datetime,
    max_attempts: int = 2,
) -> MixedProviderResult:
    """Use the existing PlannerProvider strict-call boundary, then fail closed."""

    interaction = InteractionRequest(
        interaction_id=interaction_id,
        text=utterance,
        role_hint="pilot",
        domain_hint="mixed_conversation",
        allowed_capabilities=(MIXED_DECOMPOSITION_CAPABILITY,),
    )
    request = PlannerProviderRequest(
        planner_task_id=planner_task_id,
        interaction=interaction,
        allowed_capabilities=(MIXED_DECOMPOSITION_CAPABILITY,),
        available_tools=(mixed_decomposition_tool_definition(),),
        core_instructions=(_provider_instructions(),),
        deadline=deadline,
        retry_policy=ProviderRetryPolicy(max_attempts=max_attempts),
    )
    cancellation = PlannerCancellationToken()
    run = provider.start(request)
    try:
        event = run.next_event(deadline=deadline, cancellation=cancellation)
        if isinstance(event, PlannerFailedEvent):
            return MixedProviderResult(
                status=MixedProviderStatus.PROVIDER_FAILED,
                usage=event.usage,
                error=event.error,
            )
        if not isinstance(event, PlannerToolCallsEvent) or len(event.calls) != 1:
            return MixedProviderResult(
                status=MixedProviderStatus.INVALID_OUTPUT,
                usage=getattr(event, "usage", None),
                error=_invalid_output_error(),
            )
        call = event.calls[0]
        if call.name != MIXED_DECOMPOSITION_TOOL_NAME:
            return MixedProviderResult(
                status=MixedProviderStatus.INVALID_OUTPUT,
                usage=event.usage,
                error=_invalid_output_error(),
            )
        try:
            decomposition = MixedConversationDecomposition.model_validate(
                call.arguments.root
            )
        except ValueError:
            return MixedProviderResult(
                status=MixedProviderStatus.INVALID_OUTPUT,
                usage=event.usage,
                error=_invalid_output_error(),
            )
        return MixedProviderResult(
            status=MixedProviderStatus.COMPLETED,
            decomposition=decomposition,
            usage=event.usage,
        )
    finally:
        run.cancel()


def build_mixed_composition(
    *,
    decomposition: MixedConversationDecomposition,
    identity: AtcSessionIdentity,
    utterance: str,
    interaction_id: UUID,
    vertical: GoldenTakeoffVertical,
    profile_id: CommunicationProfileId,
) -> MixedCompositionOutcome:
    """Route intent to ATC and locally compose FREE before immutable PROTECTED."""

    if profile_id is not vertical.profile_id:
        raise ValueError("composition profile must match the phraseology resolver profile")
    operational = tuple(decomposition.operational_intents)
    golden: GoldenTakeoffResult | None = None
    protected = ()
    if operational:
        if operational != (MixedOperationalIntent.TAKEOFF_CLEARANCE_REQUEST,):
            raise ValueError("unsupported operational intent")
        intent = TakeoffIntent(
            status=TakeoffIntentStatus.RECOGNIZED,
            language=decomposition.detected_input_language,
            kind=TakeoffIntentKind.TAKEOFF_CLEARANCE_REQUEST,
            matched_takeoff_cue=True,
            matched_request_cue=True,
        )
        golden = vertical.handle_recognized_intent(
            identity=identity,
            utterance=utterance,
            intent=intent,
        )
        if golden.fragment is None:
            raise RuntimeError("recognized operational intent produced no protected fragment")
        protected = (golden.fragment,)

    envelope = (
        UntrustedConversationalEnvelope(text=decomposition.free_response_text)
        if decomposition.free_response_text is not None
        else None
    )
    if envelope is None and not protected:
        return MixedCompositionOutcome(decomposition=decomposition)
    plan = ResponseCompositionPlan(
        interaction_id=interaction_id,
        communication=CommunicationContext(
            profile_id=profile_id,
            domain=(CommunicationDomain.ATC if protected else CommunicationDomain.GENERAL),
            input_language=decomposition.detected_input_language,
            operational_language=decomposition.detected_input_language,
        ),
        priority=(
            golden.semantic_unit.priority
            if golden is not None and golden.semantic_unit is not None
            else CommunicationPriority.ROUTINE
        ),
        envelope=envelope,
        protected_fragments=protected,
    )
    return MixedCompositionOutcome(
        decomposition=decomposition,
        golden_result=golden,
        plan=plan,
        final_text=compose_response_plan(plan),
    )


def compose_response_plan(plan: ResponseCompositionPlan) -> str:
    """Core-owned deterministic ordering: FREE envelope, then PROTECTED tuple."""

    protected_texts = [fragment.text for fragment in plan.protected_fragments]
    if len(protected_texts) != len(set(protected_texts)):
        raise ValueError("duplicate protected fragment")
    parts: list[str] = []
    if plan.envelope is not None and not plan.suppress_conversational_envelope:
        parts.append(plan.envelope.text)
    parts.extend(protected_texts)
    if not parts:
        raise ValueError("composition plan contains no output fragment")
    final_text = " ".join(parts)
    for protected_text in protected_texts:
        if final_text.count(protected_text) != 1:
            raise ValueError("protected fragment was altered during composition")
    return final_text


def _provider_instructions() -> str:
    return (
        "Analyze only the user's current utterance. Call the one exposed emitter "
        "exactly once. Separate FREE social/conversational meaning from OPERATIONAL "
        "meaning. The only supported operational intent is "
        "takeoff_clearance_request. Greetings are FREE kind greeting; questions like "
        "how are you may also use social_exchange. For FREE content, copy only the "
        "relevant source span and write one short natural reply to that FREE content. "
        "The FREE reply must never grant, deny, discuss, or paraphrase takeoff, and must "
        "not invent callsign, runway, state, or any operational decision. A takeoff "
        "permission/readiness request is classified with that one operational intent. "
        "Pure takeoff requests have empty FREE fields. Pure social input has no "
        "operational intent. Other aviation operations, including landing, are "
        "unsupported with no operational intent. Use ambiguous only when the utterance "
        "cannot safely establish meaning. Detect language independently of any "
        "communication profile. Never include an operational decision field."
    )


def _contains_operational_decision(text: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    forbidden = (
        r"взлет\w*\s+разреш",
        r"разреш\w*\s+взлет",
        r"cleared\s+for\s+takeoff",
        r"hold\s+(?:position|short)",
        r"полоса\s+\d",
        r"runway\s+\d",
    )
    return any(re.search(pattern, normalized) is not None for pattern in forbidden)


def _invalid_output_error() -> PlannerError:
    from orion.planner_contracts import PlannerErrorCategory, PlannerErrorCode

    return PlannerError(
        code=PlannerErrorCode.PROVIDER_PROTOCOL_ERROR,
        category=PlannerErrorCategory.PROTOCOL,
        message="Mixed decomposition provider output failed strict validation.",
        retryable=False,
    )
