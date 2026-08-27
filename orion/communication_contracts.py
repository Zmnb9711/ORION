"""Minimum provider-neutral IA-6 seams for future communication presentation."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from orion.interaction_contracts import (
    ContextReference,
    SemanticKey,
    SemanticScalar,
    SemanticText,
)
from orion.world_model_contracts import WorldFactAuthority, WorldGeneration


OpaqueVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
LanguageId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=2, max_length=35, pattern=r"^[A-Za-z0-9-]+$"
    ),
]
OperationalUnitType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$",
    ),
]


class _CommunicationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class CommunicationProfileId(StrEnum):
    ICAO = "ICAO"
    FAA_US = "FAA_US"
    NATO_MILITARY = "NATO_MILITARY"
    FAP_RUSSIAN_ATC = "FAP_RUSSIAN_ATC"


class CommunicationDomain(StrEnum):
    GENERAL = "general"
    ATC = "atc"
    AWACS_GCI = "awacs_gci"
    JTAC = "jtac"
    AAR = "aar"
    MISSION_CONTROL = "mission_control"
    NAVIGATION = "navigation"


class ConversationalLanguagePolicy(StrEnum):
    FOLLOW_USER = "follow_user"


class CommunicationPriority(StrEnum):
    ROUTINE = "routine"
    IMPORTANT = "important"
    URGENT = "urgent"
    IMMEDIATE = "immediate"


class OutputClassification(StrEnum):
    CONVERSATIONAL = "conversational"
    ADVISORY = "advisory"
    OPERATIONAL_PROTECTED = "operational_protected"


class ProtectedValueKind(StrEnum):
    GENERIC = "generic"
    CALLSIGN = "callsign"
    RUNWAY = "runway"
    HEADING = "heading"
    ALTITUDE = "altitude"
    SPEED = "speed"
    FREQUENCY = "frequency"
    TACAN = "tacan"
    LASER_CODE = "laser_code"
    COORDINATES = "coordinates"
    BRAA = "braa"


class CommunicationContext(_CommunicationModel):
    profile_id: CommunicationProfileId
    domain: CommunicationDomain = CommunicationDomain.GENERAL
    input_language: LanguageId | None = None
    conversational_language_policy: ConversationalLanguagePolicy = (
        ConversationalLanguagePolicy.FOLLOW_USER
    )
    operational_language: LanguageId | None = None
    phraseology_snapshot_id: OpaqueVersion | None = None
    phraseology_version: OpaqueVersion | None = None


class ProtectedProvenance(_CommunicationModel):
    source: ContextReference
    authority: WorldFactAuthority
    generation: WorldGeneration | None = None
    domain_origin: CommunicationDomain


class ProtectedValue(_CommunicationModel):
    key: SemanticKey
    kind: ProtectedValueKind
    value: SemanticScalar = Field(repr=False)
    unit: str | None = Field(default=None, min_length=1, max_length=40)


class OperationalSemanticUnit(_CommunicationModel):
    """Already-decided meaning; this contract never establishes operational truth."""

    unit_type: OperationalUnitType
    semantic_meaning: OperationalUnitType
    domain: CommunicationDomain
    priority: CommunicationPriority
    status: str | None = Field(default=None, min_length=1, max_length=80)
    polarity: str | None = Field(default=None, min_length=1, max_length=40)
    protected_values: tuple[ProtectedValue, ...] = Field(default=(), repr=False)
    provenance: tuple[ProtectedProvenance, ...] = ()

    @model_validator(mode="after")
    def reject_duplicate_values(self) -> Self:
        keys = [item.key for item in self.protected_values]
        if len(keys) != len(set(keys)):
            raise ValueError("OperationalSemanticUnit protected keys must be unique")
        return self


class UntrustedConversationalEnvelope(_CommunicationModel):
    text: SemanticText = Field(repr=False)
    authoritative: Literal[False] = False
    droppable: Literal[True] = True


class ProtectedOperationalFragment(_CommunicationModel):
    """Immutable Core-rendered fragment that must never be returned to Qwen."""

    text: SemanticText = Field(repr=False)
    semantic_unit: OperationalSemanticUnit
    rendered_by_core: Literal[True] = True
    renderer_version: OpaqueVersion


class ResponseCompositionPlan(_CommunicationModel):
    """Future deterministic composer input; no phraseology rendering occurs here."""

    interaction_id: UUID
    communication: CommunicationContext
    priority: CommunicationPriority
    envelope: UntrustedConversationalEnvelope | None = Field(default=None, repr=False)
    advisory: tuple[SemanticText, ...] = Field(default=(), repr=False)
    protected_fragments: tuple[ProtectedOperationalFragment, ...] = Field(
        default=(), repr=False
    )
    suppress_conversational_envelope: bool = False

    @model_validator(mode="after")
    def immediate_suppresses_envelope(self) -> Self:
        if self.priority is CommunicationPriority.IMMEDIATE:
            if not self.suppress_conversational_envelope or self.envelope is not None:
                raise ValueError(
                    "IMMEDIATE composition must suppress conversational envelope"
                )
        return self
