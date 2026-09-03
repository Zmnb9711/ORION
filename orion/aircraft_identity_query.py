"""Bounded read-only live-DCS aircraft identity MODEL C contract."""

from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from orion.aircraft_identity_presentation import (
    AVAILABLE_AIRCRAFT_MARKER,
    UNAVAILABLE_AIRCRAFT_MARKER,
    AircraftIdentityShellValidationError,
    aircraft_identity_marker,
    bind_aircraft_identity_shell,
    validate_aircraft_identity_structure,
    validate_aircraft_identity_shell,
    validate_and_bind_aircraft_identity_shell,
)
from orion.flight_context import aircraft_display_name
from orion.interaction_contracts import (
    CapabilityId,
    ContextReference,
    InteractionRequest,
    PresentationMode,
    SemanticFact,
    SemanticFactKind,
    SemanticInputIssue,
    SemanticInputStatus,
    SemanticResponse,
)
from orion.planner import (
    PlannerCancellationToken,
    PlannerProvider,
    PlannerTaskRunner,
    planner_runner,
)
from orion.planner_contracts import PlannerExecutionPolicy, ProviderRetryPolicy
from orion.semantic_response_validation import (
    SemanticClaimCategory,
    SemanticConformanceJudge,
    SemanticConformanceVerdict,
    SemanticValidationError,
    SemanticValidationErrorCode,
    SemanticValidationPolicy,
    semantic_request_from_response,
    semantic_response_with_context,
    SemanticValidationContextFact,
)
from orion.world_model import world_model
from orion.world_model_contracts import (
    OwnshipSnapshot,
    WorldFactAuthority,
    WorldFactReason,
    WorldFactSource,
    WorldFactStatus,
    WorldGeneration,
)
from orion.yandex_realtime_informational_presenter import (
    RealtimeInformationalRequest,
    YandexRealtimeInformationalPresenter,
)


AIRCRAFT_IDENTITY_CAPABILITY = CapabilityId("flight.aircraft_identity")
AIRCRAFT_IDENTITY_CONTRACT = "aircraft_identity_query"
AIRCRAFT_IDENTITY_SEMANTIC_MEANING = "flight.current_aircraft_identity"
AIRCRAFT_IDENTITY_RADIO_ENTITY = "orion.assistant.aircraft_information"
AIRCRAFT_IDENTITY_SEMANTIC_POLICY = SemanticValidationPolicy(
    policy_id="flight.current_aircraft_identity.bounded_context.v2",
    semantic_meaning=AIRCRAFT_IDENTITY_SEMANTIC_MEANING,
    allowed_known_meaning=(
        "The response states that the user's current aircraft identity is the single opaque "
        "Core marker. It may also state relevant facts explicitly supported by "
        "bounded_authoritative_context."
    ),
    allowed_unavailable_meaning=(
        "The response explicitly states that authoritative current-aircraft identity "
        "information is unavailable; the unavailable marker is not an aircraft identity value."
    ),
    factual_claim_categories=tuple(SemanticClaimCategory),
)
_AVAILABLE_MARKER = AVAILABLE_AIRCRAFT_MARKER
_UNAVAILABLE_MARKER = UNAVAILABLE_AIRCRAFT_MARKER


class AircraftIdentityIntentStatus(StrEnum):
    RECOGNIZED = "recognized"
    UNSUPPORTED = "unsupported"


class AircraftIdentityIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AircraftIdentityIntentStatus
    language: str = Field(pattern=r"^(?:ru-RU|en-US)$")


class AircraftIdentityQueryStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class AircraftIdentityQueryResult(BaseModel):
    """One immutable projection of the current World Model aircraft fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_meaning: Literal["flight.current_aircraft_identity"] = (
        AIRCRAFT_IDENTITY_SEMANTIC_MEANING
    )
    status: AircraftIdentityQueryStatus
    raw_aircraft_id: str | None = Field(default=None, max_length=160)
    display_name: str | None = Field(default=None, max_length=200)
    fact_status: WorldFactStatus
    source: WorldFactSource
    authority: WorldFactAuthority
    observed_at: datetime | None = None
    age_seconds: float | None = Field(default=None, ge=0)
    generation: WorldGeneration | None = None
    unavailable_reason: str | None = Field(default=None, max_length=120)


class AircraftIdentityResolver(Protocol):
    def resolve(self) -> AircraftIdentityQueryResult: ...


class AircraftIdentitySemanticOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: AircraftIdentityQueryResult
    semantic_response: SemanticResponse
    final_text: str = Field(min_length=1, max_length=4000)
    radio_entity_id: str = AIRCRAFT_IDENTITY_RADIO_ENTITY
    qwen_call_count: Literal[1] = 1
    qwen_fact_authority: Literal[False] = False
    qwen_response_ids: tuple[str, ...] = ()
    qwen_latency_ms: float = Field(ge=0)
    formulation_origin: Literal["qwen_validated_placeholder"] = (
        "qwen_validated_placeholder"
    )


class AircraftIdentityRealtimeCandidateOutcome(BaseModel):
    """Non-default benchmark result; it is not selected by production routing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: AircraftIdentityQueryResult
    semantic_response: SemanticResponse
    final_text: str = Field(min_length=1, max_length=4000)
    radio_entity_id: str = AIRCRAFT_IDENTITY_RADIO_ENTITY
    provider_response_id: str
    provider_fact_authority: Literal[False] = False
    first_token_latency_ms: float = Field(ge=0)
    formulation_latency_ms: float = Field(ge=0)
    validation_latency_ms: float = Field(ge=0)
    binding_latency_ms: float = Field(ge=0)
    total_latency_ms: float = Field(ge=0)
    session_reused: bool
    validation_model: Literal["grammar_reference", "semantic_conformance"] = (
        "grammar_reference"
    )
    semantic_judge_response_id: str | None = None
    formulation_origin: Literal["yandex_realtime_validated_placeholder"] = (
        "yandex_realtime_validated_placeholder"
    )


class AircraftIdentityFormulationError(AircraftIdentityShellValidationError):
    """Qwen did not preserve the bounded Core fact/presentation contract."""


class AircraftIdentityWorldSource(Protocol):
    def ownship(self) -> OwnshipSnapshot: ...


_RU_FORMS = frozenset(
    {
        "в каком самолете я нахожусь",
        "на каком самолете я сейчас нахожусь",
        "какой у меня самолет",
    }
)
_EN_FORMS = frozenset(
    {
        "what aircraft am i in",
        "what aircraft am i flying",
        "which aircraft am i flying",
    }
)


def _canonicalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip().casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", normalized)).strip()


def classify_aircraft_identity_query(text: str) -> AircraftIdentityIntent:
    """Recognize only the approved whole-utterance RU/EN query forms."""

    canonical = _canonicalize(text)
    if canonical in _RU_FORMS:
        return AircraftIdentityIntent(
            status=AircraftIdentityIntentStatus.RECOGNIZED,
            language="ru-RU",
        )
    if canonical in _EN_FORMS:
        return AircraftIdentityIntent(
            status=AircraftIdentityIntentStatus.RECOGNIZED,
            language="en-US",
        )
    language = "ru-RU" if re.search(r"[А-Яа-яЁё]", text) else "en-US"
    return AircraftIdentityIntent(
        status=AircraftIdentityIntentStatus.UNSUPPORTED,
        language=language,
    )


def _safe_display_name(raw_aircraft_id: str) -> str | None:
    candidate = aircraft_display_name(raw_aircraft_id)
    sanitized = re.sub(r"[^\w .+()/\-]+", " ", candidate, flags=re.UNICODE)
    sanitized = " ".join(sanitized.split())[:200].strip()
    return sanitized or None


def _fact_reference(result: AircraftIdentityQueryResult) -> ContextReference:
    generation = result.generation if result.generation is not None else "unknown"
    safe_generation = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(generation))[:120]
    return ContextReference(
        context_type="world_model_fact",
        reference_id=f"{result.source.value}:{safe_generation}",
    )


def _unavailable_reason(
    *,
    status: WorldFactStatus,
    reason: WorldFactReason | None,
    source: WorldFactSource,
    authority: WorldFactAuthority,
) -> str:
    if source is not WorldFactSource.DCS_EXPORT:
        return "non_live_dcs_source"
    if authority is not WorldFactAuthority.AUTHORITATIVE:
        return "non_authoritative_aircraft_identity"
    if reason is not None:
        return reason.value
    return f"world_fact_{status.value}"


class AircraftIdentityQueryService:
    """Read current DCS truth on demand; never caches or mutates World Model state."""

    def __init__(self, source: AircraftIdentityWorldSource = world_model) -> None:
        self._source = source

    def resolve(self) -> AircraftIdentityQueryResult:
        fact = self._source.ownship().aircraft
        usable = (
            fact.status is WorldFactStatus.KNOWN
            and fact.source is WorldFactSource.DCS_EXPORT
            and fact.authority is WorldFactAuthority.AUTHORITATIVE
            and fact.value is not None
        )
        raw_aircraft_id = fact.value.aircraft_type if usable and fact.value else None
        display_name = (
            _safe_display_name(raw_aircraft_id) if raw_aircraft_id is not None else None
        )
        if usable and display_name is not None:
            result = AircraftIdentityQueryResult(
                status=AircraftIdentityQueryStatus.AVAILABLE,
                raw_aircraft_id=raw_aircraft_id,
                display_name=display_name,
                fact_status=fact.status,
                source=fact.source,
                authority=fact.authority,
                observed_at=fact.observed_at,
                age_seconds=fact.age_seconds,
                generation=fact.generation,
            )
        else:
            result = AircraftIdentityQueryResult(
                status=AircraftIdentityQueryStatus.UNAVAILABLE,
                fact_status=fact.status,
                source=fact.source,
                authority=fact.authority,
                observed_at=fact.observed_at,
                age_seconds=fact.age_seconds,
                generation=fact.generation,
                unavailable_reason=(
                    "invalid_aircraft_identifier"
                    if usable
                    else _unavailable_reason(
                        status=fact.status,
                        reason=fact.reason,
                        source=fact.source,
                        authority=fact.authority,
                    )
                ),
            )
        return result


def _core_semantic_response(
    result: AircraftIdentityQueryResult,
    *,
    interaction_id: UUID,
) -> SemanticResponse:
    """Represent Core truth before presentation; this does not own final wording."""

    source = _fact_reference(result)
    facts: tuple[SemanticFact, ...] = ()
    derived: tuple[SemanticFact, ...] = ()
    unavailable: tuple[SemanticInputIssue, ...] = ()
    if result.status is AircraftIdentityQueryStatus.AVAILABLE:
        assert result.raw_aircraft_id is not None
        assert result.display_name is not None
        facts = (
            SemanticFact(
                key="flight.current_aircraft_identity.raw_dcs_id",
                value=result.raw_aircraft_id,
                kind=SemanticFactKind.AUTHORITATIVE,
                source=source,
            ),
        )
        derived = (
            SemanticFact(
                key="flight.current_aircraft_identity.display_name",
                value=result.display_name,
                kind=SemanticFactKind.DERIVED,
                source=source,
            ),
        )
    else:
        unavailable = (
            SemanticInputIssue(
                key=AIRCRAFT_IDENTITY_SEMANTIC_MEANING,
                status=SemanticInputStatus.UNAVAILABLE,
                reason=result.unavailable_reason or "live_dcs_aircraft_unavailable",
                source=source,
            ),
        )
    return SemanticResponse(
        interaction_id=interaction_id,
        capability=AIRCRAFT_IDENTITY_CAPABILITY,
        presentation_mode=PresentationMode.NATURALIZE,
        authoritative_facts=facts,
        derived_results=derived,
        unavailable_inputs=unavailable,
    )


def _formulation_instruction(
    result: AircraftIdentityQueryResult,
    *,
    language: str,
) -> str:
    marker = (
        _AVAILABLE_MARKER
        if result.status is AircraftIdentityQueryStatus.AVAILABLE
        else _UNAVAILABLE_MARKER
    )
    payload = json.dumps(
        {
            "semantic_meaning": result.semantic_meaning,
            "status": result.status.value,
            "raw_dcs_aircraft_id": result.raw_aircraft_id,
            "display_name": result.display_name,
            "fact_status": result.fact_status.value,
            "source": result.source.value,
            "authority": result.authority.value,
            "unavailable_reason": result.unavailable_reason,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "This is an informational wording step after Core resolved the fact. "
        "Core/WorldModel exclusively owns the aircraft fact; you have no fact authority. "
        f"Authoritative Core state: {payload}. "
        f"Write one concise natural {'Russian' if language == 'ru-RU' else 'English'} sentence "
        f"in recommendation using the exact marker {marker} exactly once. "
        "Do not output an aircraft identifier, model, nickname, fixture, default, or guess; "
        "the Core will replace the marker after validation. Return capability=null, "
        "presentation_mode=naturalize, empty authoritative_facts, derived_results, "
        "assumptions, unavailable_inputs, and warnings, and verbatim_text=null."
    )


def _validate_formulation_draft(
    draft: SemanticResponse,
    result: AircraftIdentityQueryResult,
    *,
    language: str,
) -> str:
    if (
        draft.capability is not None
        or draft.presentation_mode is not PresentationMode.NATURALIZE
        or draft.authoritative_facts
        or draft.derived_results
        or draft.assumptions
        or draft.unavailable_inputs
        or draft.warnings
        or draft.verbatim_text is not None
        or draft.recommendation is None
    ):
        raise AircraftIdentityFormulationError(
            "Qwen formulation exceeded the no-fact-authority response shape"
        )
    try:
        return validate_and_bind_aircraft_identity_shell(
            draft.recommendation,
            result,
            language=language,
        )
    except AircraftIdentityShellValidationError as exc:
        raise AircraftIdentityFormulationError(str(exc)) from exc


class AircraftIdentityFormulationService:
    """Resolve Core truth, let Qwen phrase a marker shell, then bind the fact."""

    def __init__(
        self,
        *,
        query: AircraftIdentityResolver | None = None,
        planner: PlannerTaskRunner = planner_runner,
    ) -> None:
        self._query = query or AircraftIdentityQueryService()
        self._planner = planner

    def execute(
        self,
        *,
        provider: PlannerProvider,
        interaction_id: UUID,
        utterance: str,
        language: str,
        deadline: datetime | None = None,
        cancellation: PlannerCancellationToken | None = None,
    ) -> AircraftIdentitySemanticOutcome:
        result = self._query.resolve()
        core_response = _core_semantic_response(result, interaction_id=interaction_id)
        selected_deadline = deadline or datetime.now(UTC) + timedelta(seconds=60)
        execution = self._planner.execute(
            InteractionRequest(
                interaction_id=interaction_id,
                text=utterance,
                role_hint="pilot",
                domain_hint="general",
                allowed_capabilities=(),
            ),
            provider,
            PlannerExecutionPolicy(
                actor_id="orion-aircraft-identity-formulation",
                provider_id=provider.provider_id,
                permissions=(),
                core_instructions=(
                    _formulation_instruction(result, language=language),
                ),
                deadline=selected_deadline,
                max_tool_rounds=0,
                provider_retry=ProviderRetryPolicy(max_attempts=2),
            ),
            cancellation=cancellation,
        )
        if execution.response is None:
            code = execution.error.code.value if execution.error else "unknown"
            raise AircraftIdentityFormulationError(
                f"Qwen aircraft formulation failed safely: {code}"
            )
        final_text = _validate_formulation_draft(
            execution.response,
            result,
            language=language,
        )
        final_response = SemanticResponse(
            interaction_id=interaction_id,
            capability=AIRCRAFT_IDENTITY_CAPABILITY,
            presentation_mode=PresentationMode.VERBATIM,
            authoritative_facts=core_response.authoritative_facts,
            derived_results=core_response.derived_results,
            unavailable_inputs=core_response.unavailable_inputs,
            verbatim_text=final_text,
        )
        usage = execution.task.usage
        return AircraftIdentitySemanticOutcome(
            result=result,
            semantic_response=final_response,
            final_text=final_text,
            qwen_response_ids=(usage.provider_request_ids if usage else ()),
            qwen_latency_ms=execution.task.total_latency_ms,
        )


class AircraftIdentityRealtimeCandidateService:
    """Benchmark-only Realtime wording path over the unchanged Core truth gate."""

    def __init__(self, *, query: AircraftIdentityResolver | None = None) -> None:
        self._query = query or AircraftIdentityQueryService()

    async def execute(
        self,
        *,
        presenter: YandexRealtimeInformationalPresenter,
        interaction_id: UUID,
        language: Literal["ru-RU", "en-US"],
        semantic_validator: SemanticConformanceJudge | None = None,
        authoritative_context: tuple[SemanticValidationContextFact, ...] = (),
    ) -> AircraftIdentityRealtimeCandidateOutcome:
        total_started = time.perf_counter()
        if authoritative_context and semantic_validator is None:
            raise SemanticValidationError(
                SemanticValidationErrorCode.INVALID_CORE_CONTRACT,
                "Additional Core facts require semantic conformance validation",
            )
        result = self._query.resolve()
        core_response = semantic_response_with_context(
            _core_semantic_response(result, interaction_id=interaction_id),
            authoritative_context,
        )
        request = RealtimeInformationalRequest(
            request_id=interaction_id.hex,
            semantic_meaning=result.semantic_meaning,
            language=language,
            required_marker=aircraft_identity_marker(result),
            fact_status=result.status.value,
            fact_source=result.source.value,
            fact_authority=result.authority.value,
            fact_generation=result.generation,
            freshness_status=result.fact_status.value,
            authoritative_context=authoritative_context,
        )
        presentation = await presenter.formulate(request)
        validation_started = time.perf_counter()
        semantic_judge_response_id: str | None = None
        if semantic_validator is None:
            try:
                validated_shell = validate_aircraft_identity_shell(
                    presentation.output_text,
                    result,
                    language=language,
                )
            except AircraftIdentityShellValidationError as exc:
                presenter.record_event(
                    "formulation_failed",
                    correlation_id=request.request_id,
                    provider=presenter.provider_id,
                    error_type="validation_failed",
                )
                raise AircraftIdentityFormulationError(str(exc), code=exc.code) from exc
            validation_model: Literal["grammar_reference", "semantic_conformance"] = (
                "grammar_reference"
            )
        else:
            validated_shell = validate_aircraft_identity_structure(
                presentation.output_text,
                result,
                language=language,
                allow_contextual_identifiers=bool(authoritative_context),
            )
            semantic_request = semantic_request_from_response(
                core_response,
                policy=AIRCRAFT_IDENTITY_SEMANTIC_POLICY,
                language=language,
                fact_state=(
                    "known"
                    if result.status is AircraftIdentityQueryStatus.AVAILABLE
                    else "unavailable"
                ),
                required_marker=aircraft_identity_marker(result),
                candidate_text=validated_shell,
                authoritative_context=authoritative_context,
            )
            decision = await semantic_validator.evaluate_semantic_conformance(
                semantic_request
            )
            semantic_judge_response_id = decision.provider_response_id
            if decision.verdict is not SemanticConformanceVerdict.CONFORMANT:
                presenter.record_event(
                    "formulation_failed",
                    correlation_id=request.request_id,
                    provider=presenter.provider_id,
                    error_type=SemanticValidationErrorCode.JUDGE_REJECTED.value,
                    unsupported_category_count=len(decision.unsupported_categories),
                )
                raise SemanticValidationError(
                    SemanticValidationErrorCode.JUDGE_REJECTED,
                    "Natural informational response exceeded Core semantic meaning",
                    unsupported_categories=decision.unsupported_categories,
                    latency_ms=decision.latency_ms,
                )
            validation_model = "semantic_conformance"
        validation_finished = time.perf_counter()
        validation_latency_ms = (validation_finished - validation_started) * 1000
        presenter.record_event(
            "formulation_validation_completed",
            correlation_id=request.request_id,
            provider=presenter.provider_id,
            status="pass",
            latency_ms=round(validation_latency_ms, 3),
            provider_fact_authority=False,
        )
        binding_started = time.perf_counter()
        final_text = bind_aircraft_identity_shell(
            validated_shell,
            result,
            language=language,
        )
        binding_finished = time.perf_counter()
        binding_latency_ms = (binding_finished - binding_started) * 1000
        presenter.record_event(
            "core_fact_binding_completed",
            correlation_id=request.request_id,
            provider=presenter.provider_id,
            status="pass",
            latency_ms=round(binding_latency_ms, 3),
            fact_source=result.source.value,
            fact_authority=result.authority.value,
            fact_generation=str(result.generation or "unknown"),
            provider_fact_authority=False,
        )
        final_response = SemanticResponse(
            interaction_id=interaction_id,
            capability=AIRCRAFT_IDENTITY_CAPABILITY,
            presentation_mode=PresentationMode.VERBATIM,
            authoritative_facts=core_response.authoritative_facts,
            derived_results=core_response.derived_results,
            unavailable_inputs=core_response.unavailable_inputs,
            verbatim_text=final_text,
        )
        return AircraftIdentityRealtimeCandidateOutcome(
            result=result,
            semantic_response=final_response,
            final_text=final_text,
            provider_response_id=presentation.provider_response_id,
            first_token_latency_ms=presentation.first_token_latency_ms,
            formulation_latency_ms=presentation.complete_latency_ms,
            validation_latency_ms=validation_latency_ms,
            binding_latency_ms=binding_latency_ms,
            total_latency_ms=(binding_finished - total_started) * 1000,
            session_reused=presentation.session_reused,
            validation_model=validation_model,
            semantic_judge_response_id=semantic_judge_response_id,
        )


aircraft_identity_query = AircraftIdentityQueryService()
