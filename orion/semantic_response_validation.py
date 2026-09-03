"""Provider-neutral semantic conformance contracts for informational wording."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orion.interaction_contracts import PresentationMode, SemanticResponse


MAX_SEMANTIC_CANDIDATE_LENGTH = 300


class SemanticClaimCategory(StrEnum):
    SECOND_ENTITY_IDENTITY = "second_entity_identity"
    ALTITUDE = "altitude"
    FUEL = "fuel"
    HEADING = "heading"
    POSITION = "position"
    RADIO_FREQUENCY = "radio_frequency"
    TACAN = "tacan"
    MISSION_STATE = "mission_state"
    NUMERIC_IDENTIFIER = "numeric_identifier"
    OPERATIONAL_ASSERTION = "operational_assertion"
    UNCERTAINTY_DRIFT = "uncertainty_drift"
    WRONG_FACT_STATE = "wrong_fact_state"
    UNRELATED_FACT = "unrelated_fact"


class SemanticConformanceVerdict(StrEnum):
    CONFORMANT = "conformant"
    NONCONFORMANT = "nonconformant"


class SemanticValidationErrorCode(StrEnum):
    INVALID_CORE_CONTRACT = "invalid_core_contract"
    JUDGE_PROTOCOL = "semantic_judge_protocol"
    JUDGE_REJECTED = "semantic_judge_rejected"
    JUDGE_UNAVAILABLE = "semantic_judge_unavailable"


class SemanticValidationError(RuntimeError):
    """Semantic validation failed closed before the response reached downstream."""

    def __init__(
        self,
        code: SemanticValidationErrorCode,
        message: str,
        *,
        unsupported_categories: tuple[SemanticClaimCategory, ...] = (),
        latency_ms: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.unsupported_categories = unsupported_categories
        self.latency_ms = latency_ms


class SemanticValidationPolicy(BaseModel):
    """One bounded semantic meaning; multi-fact validation is intentionally absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-z][a-z0-9_.-]+$")
    semantic_meaning: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_.-]+$",
    )
    allowed_known_meaning: str = Field(min_length=1, max_length=400)
    allowed_unavailable_meaning: str = Field(min_length=1, max_length=400)
    prohibited_categories: tuple[SemanticClaimCategory, ...]

    @model_validator(mode="after")
    def validate_categories(self) -> SemanticValidationPolicy:
        if not self.prohibited_categories:
            raise ValueError("semantic policy must prohibit unsupported claim categories")
        if len(self.prohibited_categories) != len(set(self.prohibited_categories)):
            raise ValueError("semantic policy categories must be unique")
        return self


class SemanticConformanceRequest(BaseModel):
    """Fact-free judge request derived from one Core-owned SemanticResponse."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    semantic_response_id: UUID
    interaction_id: UUID
    policy: SemanticValidationPolicy
    language: Literal["ru-RU", "en-US"]
    fact_state: Literal["known", "unavailable"]
    required_marker: str = Field(min_length=5, max_length=80)
    candidate_text: str = Field(min_length=1, max_length=MAX_SEMANTIC_CANDIDATE_LENGTH)
    provider_fact_authority: Literal[False] = False

    def provider_input(self) -> str:
        allowed_meaning = (
            self.policy.allowed_known_meaning
            if self.fact_state == "known"
            else self.policy.allowed_unavailable_meaning
        )
        return json.dumps(
            {
                "contract": "orion.semantic_conformance.v1",
                "request_id": self.request_id,
                "semantic_meaning": self.policy.semantic_meaning,
                "language": self.language,
                "fact_state": self.fact_state,
                "required_marker": self.required_marker,
                "allowed_meaning": allowed_meaning,
                "candidate_text": self.candidate_text,
                "prohibited_claim_categories": [
                    item.value for item in self.policy.prohibited_categories
                ],
                "provider_fact_authority": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def response_instructions(self) -> str:
        return (
            "Act only as a strict semantic-conformance classifier for this response. "
            "Evaluate the meaning of candidate_text against allowed_meaning; do not judge "
            "style, punctuation, word order, or grammar. Treat required_marker as one opaque "
            "Core-owned fact. Mark nonconformant if the candidate asserts, implies, guesses, "
            "qualifies, or expresses uncertainty about anything beyond allowed_meaning, or if "
            "its fact state differs. Return one JSON object with a boolean conformant field "
            "and a short reason field: "
            '{"conformant":true,"reason":"only allowed meaning"} or '
            '{"conformant":false,"reason":"unsupported meaning"}. '
            "Do not rewrite candidate_text and do not add any other field."
        )


class SemanticConformanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    verdict: SemanticConformanceVerdict
    unsupported_categories: tuple[SemanticClaimCategory, ...] = ()
    provider_id: str = Field(min_length=1, max_length=120)
    provider_response_id: str = Field(min_length=1, max_length=200)
    latency_ms: float = Field(ge=0)
    session_reused: bool
    provider_fact_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_verdict(self) -> SemanticConformanceResult:
        if self.verdict is SemanticConformanceVerdict.CONFORMANT:
            if self.unsupported_categories:
                raise ValueError("conformant result cannot contain unsupported categories")
        elif not self.unsupported_categories:
            raise ValueError("nonconformant result requires an unsupported category")
        return self


class _SemanticJudgeWireResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: SemanticConformanceVerdict
    unsupported_categories: tuple[SemanticClaimCategory, ...] = ()

    @model_validator(mode="after")
    def validate_verdict(self) -> _SemanticJudgeWireResult:
        if self.verdict is SemanticConformanceVerdict.CONFORMANT:
            if self.unsupported_categories:
                raise ValueError("conformant judge output contained unsupported categories")
        elif not self.unsupported_categories:
            raise ValueError("nonconformant judge output omitted unsupported categories")
        return self


class _ProviderBooleanJudgeWireResult(BaseModel):
    """Current Yandex Realtime classifier shape; the reason is discarded immediately."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conformant: bool
    reason: str = Field(min_length=1, max_length=800)


def _bounded_json_payload(output_text: str) -> str:
    """Accept plain JSON or one provider-added JSON fence, and nothing else."""

    normalized = output_text.strip()
    if not normalized.startswith("```"):
        return normalized
    lines = normalized.splitlines()
    if len(lines) < 3 or lines[0] not in {"```", "```json"} or lines[-1] != "```":
        raise ValueError("invalid provider JSON fence")
    if any("```" in line for line in lines[1:-1]):
        raise ValueError("nested provider JSON fence")
    return "\n".join(lines[1:-1]).strip()


class SemanticConformanceJudge(Protocol):
    async def evaluate_semantic_conformance(
        self,
        request: SemanticConformanceRequest,
    ) -> SemanticConformanceResult: ...


def semantic_request_from_response(
    response: SemanticResponse,
    *,
    policy: SemanticValidationPolicy,
    language: Literal["ru-RU", "en-US"],
    fact_state: Literal["known", "unavailable"],
    required_marker: str,
    candidate_text: str,
) -> SemanticConformanceRequest:
    """Bind a judge request to a typed Core response without exposing fact values."""

    if response.presentation_mode is not PresentationMode.NATURALIZE:
        raise SemanticValidationError(
            SemanticValidationErrorCode.INVALID_CORE_CONTRACT,
            "Semantic validation requires a Core NATURALIZE response",
        )
    known = bool(response.authoritative_facts or response.derived_results)
    unavailable = bool(response.unavailable_inputs)
    if known == unavailable or known != (fact_state == "known"):
        raise SemanticValidationError(
            SemanticValidationErrorCode.INVALID_CORE_CONTRACT,
            "Semantic validation fact state does not match the Core response",
        )
    if response.capability is None:
        raise SemanticValidationError(
            SemanticValidationErrorCode.INVALID_CORE_CONTRACT,
            "Semantic validation requires a typed Core capability",
        )
    return SemanticConformanceRequest(
        request_id=f"semantic-{uuid4().hex}",
        semantic_response_id=response.response_id,
        interaction_id=response.interaction_id,
        policy=policy,
        language=language,
        fact_state=fact_state,
        required_marker=required_marker,
        candidate_text=" ".join(candidate_text.split()),
    )


def parse_semantic_judge_output(
    output_text: str,
    *,
    request: SemanticConformanceRequest,
    provider_id: str,
    provider_response_id: str,
    latency_ms: float,
    session_reused: bool,
) -> SemanticConformanceResult:
    """Parse one strict provider decision; every malformed result fails closed."""

    try:
        raw = json.loads(_bounded_json_payload(output_text))
        if isinstance(raw, dict) and "conformant" in raw:
            provider_result = _ProviderBooleanJudgeWireResult.model_validate(raw)
            if provider_result.conformant:
                parsed = _SemanticJudgeWireResult(
                    verdict=SemanticConformanceVerdict.CONFORMANT,
                    unsupported_categories=(),
                )
            else:
                if SemanticClaimCategory.UNRELATED_FACT not in request.policy.prohibited_categories:
                    raise ValueError("policy has no generic unsupported-meaning category")
                parsed = _SemanticJudgeWireResult(
                    verdict=SemanticConformanceVerdict.NONCONFORMANT,
                    unsupported_categories=(SemanticClaimCategory.UNRELATED_FACT,),
                )
        else:
            parsed = _SemanticJudgeWireResult.model_validate(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SemanticValidationError(
            SemanticValidationErrorCode.JUDGE_PROTOCOL,
            "Semantic judge returned an invalid bounded decision",
        ) from exc
    prohibited = set(request.policy.prohibited_categories)
    if any(item not in prohibited for item in parsed.unsupported_categories):
        raise SemanticValidationError(
            SemanticValidationErrorCode.JUDGE_PROTOCOL,
            "Semantic judge returned an out-of-contract category",
        )
    return SemanticConformanceResult(
        request_id=request.request_id,
        verdict=parsed.verdict,
        unsupported_categories=parsed.unsupported_categories,
        provider_id=provider_id,
        provider_response_id=provider_response_id,
        latency_ms=latency_ms,
        session_reused=session_reused,
    )


__all__ = [
    "MAX_SEMANTIC_CANDIDATE_LENGTH",
    "SemanticClaimCategory",
    "SemanticConformanceJudge",
    "SemanticConformanceRequest",
    "SemanticConformanceResult",
    "SemanticConformanceVerdict",
    "SemanticValidationError",
    "SemanticValidationErrorCode",
    "SemanticValidationPolicy",
    "parse_semantic_judge_output",
    "semantic_request_from_response",
]
