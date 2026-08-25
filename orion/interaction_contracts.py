"""Provider- and transport-neutral contracts for ORION interaction routing.

IA-0 defines data shapes only.  This module deliberately has no runtime,
provider, transport, DCS, SRS, planner, or routing dependency.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_core import core_schema


_CAPABILITY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*$"
)
_SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
_SAFE_HINT_PATTERN = r"^[a-z][a-z0-9_.-]*$"
_SAFE_REASON_PATTERN = r"^[a-z][a-z0-9_.:-]*$"

CorrelationId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        pattern=_SAFE_IDENTIFIER_PATTERN,
    ),
]
SemanticHint = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=_SAFE_HINT_PATTERN,
    ),
]
DiagnosticReason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        pattern=_SAFE_REASON_PATTERN,
    ),
]
SemanticText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
]
SemanticKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*$",
    ),
]
UnitName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=40),
]
SemanticScalar = str | int | float | bool


class CapabilityId(str):
    """Stable dotted identifier independent of handlers and provider tool names."""

    _MAX_LENGTH = 160

    def __new__(cls, value: str) -> Self:
        if not isinstance(value, str):
            raise TypeError("CapabilityId must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("CapabilityId must not be empty")
        if len(normalized) > cls._MAX_LENGTH:
            raise ValueError("CapabilityId must not exceed 160 characters")
        if _CAPABILITY_PATTERN.fullmatch(normalized) is None:
            raise ValueError(
                "CapabilityId must contain lowercase dotted identifier segments"
            )
        return str.__new__(cls, normalized)

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: object,
        handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(str))


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ContextReference(_ContractModel):
    """Opaque Core-owned context identity; it contains no context payload."""

    context_type: SemanticHint
    reference_id: CorrelationId


class InteractionRequest(_ContractModel):
    """One semantic user interaction entering future ORION routing."""

    interaction_id: UUID = Field(default_factory=uuid4)
    session_id: CorrelationId | None = None
    turn_id: CorrelationId | None = None
    text: SemanticText = Field(repr=False)
    role_hint: SemanticHint | None = None
    domain_hint: SemanticHint | None = None
    context_references: tuple[ContextReference, ...] = ()
    allowed_capabilities: tuple[CapabilityId, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("InteractionRequest.created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def reject_duplicate_references(self) -> Self:
        references = [
            (item.context_type, item.reference_id)
            for item in self.context_references
        ]
        if len(references) != len(set(references)):
            raise ValueError("InteractionRequest context references must be unique")
        if len(self.allowed_capabilities) != len(set(self.allowed_capabilities)):
            raise ValueError("InteractionRequest allowed capabilities must be unique")
        return self


class RouteMode(StrEnum):
    FAST = "fast"
    PLANNER = "planner"
    UNAVAILABLE = "unavailable"


class RouteDecision(_ContractModel):
    """Provider-neutral result produced by a future Interaction Router."""

    interaction_id: UUID
    route: RouteMode
    reason: DiagnosticReason
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    selected_capability: CapabilityId | None = None
    candidate_capabilities: tuple[CapabilityId, ...] = ()

    @model_validator(mode="after")
    def reject_duplicate_candidates(self) -> Self:
        if len(self.candidate_capabilities) != len(set(self.candidate_capabilities)):
            raise ValueError("RouteDecision candidate capabilities must be unique")
        if (
            self.selected_capability is not None
            and self.candidate_capabilities
            and self.selected_capability not in self.candidate_capabilities
        ):
            raise ValueError(
                "RouteDecision selected capability must be one of its candidates"
            )
        return self


class PresentationMode(StrEnum):
    NATURALIZE = "naturalize"
    VERBATIM = "verbatim"


class SemanticFactKind(StrEnum):
    AUTHORITATIVE = "authoritative"
    DERIVED = "derived"


class SemanticInputStatus(StrEnum):
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class SemanticFact(_ContractModel):
    """One known scalar fact or deterministic derived value."""

    key: SemanticKey
    value: SemanticScalar = Field(repr=False)
    kind: SemanticFactKind
    unit: UnitName | None = None
    source: ContextReference | None = None


class SemanticInputIssue(_ContractModel):
    """An input that Core could not authoritatively supply."""

    key: SemanticKey
    status: SemanticInputStatus
    reason: DiagnosticReason
    source: ContextReference | None = None


class SemanticResponse(_ContractModel):
    """Semantic result shared by future deterministic and Planner paths."""

    response_id: UUID = Field(default_factory=uuid4)
    interaction_id: UUID
    capability: CapabilityId | None = None
    presentation_mode: PresentationMode = PresentationMode.NATURALIZE
    authoritative_facts: tuple[SemanticFact, ...] = Field(
        default=(),
        repr=False,
    )
    derived_results: tuple[SemanticFact, ...] = Field(default=(), repr=False)
    recommendation: SemanticText | None = Field(default=None, repr=False)
    assumptions: tuple[SemanticText, ...] = Field(default=(), repr=False)
    unavailable_inputs: tuple[SemanticInputIssue, ...] = Field(
        default=(),
        repr=False,
    )
    warnings: tuple[SemanticText, ...] = Field(default=(), repr=False)
    verbatim_text: SemanticText | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_semantic_shape(self) -> Self:
        if self.presentation_mode is PresentationMode.VERBATIM:
            if self.verbatim_text is None:
                raise ValueError("VERBATIM SemanticResponse requires verbatim_text")
        elif self.verbatim_text is not None:
            raise ValueError("NATURALIZE SemanticResponse must not contain verbatim_text")

        for fact in self.authoritative_facts:
            if fact.kind is not SemanticFactKind.AUTHORITATIVE:
                raise ValueError(
                    "authoritative_facts must contain authoritative SemanticFact values"
                )
        for fact in self.derived_results:
            if fact.kind is not SemanticFactKind.DERIVED:
                raise ValueError("derived_results must contain derived SemanticFact values")

        fact_keys = [
            *(fact.key for fact in self.authoritative_facts),
            *(fact.key for fact in self.derived_results),
        ]
        if len(fact_keys) != len(set(fact_keys)):
            raise ValueError("SemanticResponse fact keys must be unique")
        unavailable_keys = [item.key for item in self.unavailable_inputs]
        if len(unavailable_keys) != len(set(unavailable_keys)):
            raise ValueError("SemanticResponse unavailable input keys must be unique")
        if set(fact_keys).intersection(unavailable_keys):
            raise ValueError(
                "SemanticResponse inputs cannot be both known and unavailable"
            )

        has_semantics = any(
            (
                self.authoritative_facts,
                self.derived_results,
                self.recommendation,
                self.assumptions,
                self.unavailable_inputs,
                self.warnings,
                self.verbatim_text,
            )
        )
        if not has_semantics:
            raise ValueError("SemanticResponse must contain a semantic result")
        return self
