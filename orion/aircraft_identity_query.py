"""Bounded read-only live-DCS aircraft identity MODEL C contract."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from orion.aircraft_knowledge import aircraft_knowledge
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
from orion.world_model import world_model
from orion.world_model_contracts import (
    OwnshipSnapshot,
    WorldFactAuthority,
    WorldFactReason,
    WorldFactSource,
    WorldFactStatus,
    WorldGeneration,
)


AIRCRAFT_IDENTITY_CAPABILITY = CapabilityId("flight.aircraft_identity")
AIRCRAFT_IDENTITY_CONTRACT = "aircraft_identity_query"
AIRCRAFT_IDENTITY_SEMANTIC_MEANING = "flight.current_aircraft_identity"
AIRCRAFT_IDENTITY_RADIO_ENTITY = "orion.assistant.aircraft_information"
_AVAILABLE_MARKER = "{{aircraft_identity}}"
_UNAVAILABLE_MARKER = "{{aircraft_unavailable}}"


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


class AircraftIdentityFormulationError(RuntimeError):
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
    marker = (
        _AVAILABLE_MARKER
        if result.status is AircraftIdentityQueryStatus.AVAILABLE
        else _UNAVAILABLE_MARKER
    )
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
    text = " ".join(draft.recommendation.split())
    if not text or len(text) > 300 or text.count(marker) != 1:
        raise AircraftIdentityFormulationError(
            "Qwen formulation did not preserve exactly one Core substitution marker"
        )
    other_marker = (
        _UNAVAILABLE_MARKER
        if marker == _AVAILABLE_MARKER
        else _AVAILABLE_MARKER
    )
    if other_marker in text or "{{" in text.replace(marker, ""):
        raise AircraftIdentityFormulationError(
            "Qwen formulation introduced an unsupported substitution marker"
        )
    shell = text.replace(marker, "")
    lowered = shell.casefold()
    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", shell))
    if (language == "ru-RU" and not has_cyrillic) or (
        language == "en-US" and has_cyrillic
    ):
        raise AircraftIdentityFormulationError(
            "Qwen formulation did not follow the input language"
        )
    if re.search(r"[\d/_+]", shell):
        raise AircraftIdentityFormulationError(
            "Qwen formulation introduced an aircraft-like identifier outside Core marker"
        )
    forbidden = {
        item.casefold()
        for profile in aircraft_knowledge.list_profiles()
        for item in {profile.aircraft_id, profile.display_name, *profile.aliases}
        if len(item.strip()) >= 3
    }
    if any(item in lowered for item in forbidden):
        raise AircraftIdentityFormulationError(
            "Qwen formulation introduced an aircraft identity outside Core marker"
        )
    if result.raw_aircraft_id and result.raw_aircraft_id.casefold() in lowered:
        raise AircraftIdentityFormulationError(
            "Qwen formulation copied the raw DCS identity outside Core marker"
        )
    if result.display_name and result.display_name.casefold() in lowered:
        raise AircraftIdentityFormulationError(
            "Qwen formulation copied the display identity outside Core marker"
        )
    replacement = (
        result.display_name
        if result.status is AircraftIdentityQueryStatus.AVAILABLE
        else (
            "данные о текущем самолёте из DCS недоступны"
            if language == "ru-RU"
            else "current aircraft identity from DCS is unavailable"
        )
    )
    if not replacement:
        raise AircraftIdentityFormulationError("Core aircraft substitution is unavailable")
    final_text = text.replace(marker, replacement)
    if result.display_name and final_text.count(result.display_name) != 1:
        raise AircraftIdentityFormulationError(
            "Final wording did not preserve the exact Core aircraft display identity"
        )
    return final_text


class AircraftIdentityFormulationService:
    """Resolve Core truth, let Qwen phrase a marker shell, then bind the fact."""

    def __init__(
        self,
        *,
        query: AircraftIdentityQueryService | None = None,
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


aircraft_identity_query = AircraftIdentityQueryService()
