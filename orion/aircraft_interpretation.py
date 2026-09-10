"""IA continuation: untrusted language proposal, never a simulator fact.

The input surface is bounded ordinary Russian, not an aircraft phrase list.
Existing resolved routes must run first. Operational exclusions only narrow
this first read-only scope; they never select aircraft identity.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from orion.planner import PlannerCancellationToken
from orion.conversational_core import normalize_candidate_envelope
from orion.conversational_contracts import ConversationFailure

SCOPE = "ia.natural-language.aircraft-identity.v1"
INTERPRETER_PROVIDER = "yandex.qwen3.6-35b-a3b.interpretation"
WARM_INTERPRETER_PROVIDER = "yandex.realtime.aircraft-interpretation"
InterpretationProviderId = Literal["yandex.qwen3.6-35b-a3b.interpretation", "yandex.realtime.aircraft-interpretation"]


class InterpretationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class AircraftIntent(InterpretationModel):
    capability: Literal["aircraft.identity", "not_applicable"]


class InterpretationRequest(InterpretationModel):
    scope: Literal["ia.natural-language.aircraft-identity.v1"] = SCOPE
    interaction_id: UUID
    operation_id: UUID
    source_text: str = Field(min_length=1, max_length=500, repr=False)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deadline: datetime
    expected_provider: InterpretationProviderId = INTERPRETER_PROVIDER

    @field_validator("deadline")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("interpretation_naive_deadline")
        return value


class AircraftProposal(InterpretationModel):
    """Correlation is attached by adapter, not permission granted by a model."""
    request: InterpretationRequest
    provider_id: InterpretationProviderId = INTERPRETER_PROVIDER
    response_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:/-]+$")
    intent: AircraftIntent


class AircraftAdmission(InterpretationModel):
    request: InterpretationRequest
    response_id: str
    capability: Literal["world.ownship.read"] = "world.ownship.read"


class AircraftInterpreter(Protocol):
    def interpret(self, request: InterpretationRequest,
                  cancellation: PlannerCancellationToken) -> AircraftProposal: ...


class InterpretationCleanupError(RuntimeError):
    """Provider-neutral ownership failure; must not become ordinary abstention."""


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class InterpretationParseError(ValueError):
    """Safe parsing stage only; never serialize provider text in diagnostics."""


def normalize_intent_envelope(text: str) -> str:
    if not isinstance(text, str) or len(text.encode("utf-8")) > 256:
        raise InterpretationParseError("ENVELOPE_INVALID")
    try:
        return normalize_candidate_envelope(text)
    except ConversationFailure:
        raise InterpretationParseError("ENVELOPE_INVALID") from None


def parse_intent(text: str) -> AircraftIntent:
    normalized = normalize_intent_envelope(text)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InterpretationParseError("JSON_INVALID")
            result[key] = value
        return result

    try:
        value = json.loads(normalized, object_pairs_hook=unique)
    except json.JSONDecodeError:
        raise InterpretationParseError("JSON_INVALID") from None
    try:
        return AircraftIntent.model_validate(value, strict=True)
    except ValidationError:
        raise InterpretationParseError("SCHEMA_INVALID") from None


def eligible_aircraft_interpretation(text: str, language: str) -> bool:
    # No positive aircraft keywords or paraphrase templates. Syntax/size/language
    # and excluded operational domains are the first-slice eligibility boundary.
    if language != "ru-RU" or not 3 <= len(text) <= 500:
        return False
    if re.fullmatch(r"[А-Яа-яЁё\s,.!?—-]+", text) is None:
        return False
    words = re.findall(r"[а-я]+", text.casefold().replace("ё", "е"))
    if not 2 <= len(words) <= 60:
        return False
    # Exclusions, NOT intent recognition. Commands/other fact families remain
    # unsupported here; no authority is inferred from passing this check.
    excluded = ("взлет", "взлёт", "взлет", "посад", "садит", "взлетать", "рулен", "рулеж",
                "курс", "координат", "топлив", "танкер", "атак", "цель", "целям", "огонь",
                "диспетчер", "разреш", "поворач", "высот", "скорост", "погод", "авакс", "джитак")
    return not any(word.startswith(prefix) for word in words for prefix in excluded)
