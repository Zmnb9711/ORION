"""Bounded social/aircraft contracts. No provider wording or operational facts."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orion.tool_gateway_contracts import ToolReceipt
from orion.world_model_contracts import WorldFactAuthority, WorldFactSource, WorldFactStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class HybridRoute(StrEnum):
    FREE_ONLY = "FREE_ONLY"
    FREE_PLUS_AIRCRAFT_IDENTITY = "FREE_PLUS_AIRCRAFT_IDENTITY"
    AIRCRAFT_IDENTITY = "AIRCRAFT_IDENTITY"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"


class SocialAct(StrEnum):
    GREETING = "GREETING"
    THANKS_ACKNOWLEDGEMENT = "THANKS_ACKNOWLEDGEMENT"
    SOCIAL_WELLBEING_QUERY = "SOCIAL_WELLBEING_QUERY"


class SourceSpan(StrictModel):
    start: int = Field(ge=0, le=4000, strict=True)
    end: int = Field(ge=1, le=4000, strict=True)
    act: Literal["GREETING", "THANKS_ACKNOWLEDGEMENT", "SOCIAL_WELLBEING_QUERY", "AIRCRAFT_IDENTITY_QUERY"]


class HybridAircraftDecomposition(StrictModel):
    classification: HybridRoute
    language: Literal["ru-RU"]
    spans: tuple[SourceSpan, ...] = Field(max_length=3)


class AircraftIdentityQueryResult(StrictModel):
    """Only aircraft projection plus the original, not reconstructed, receipt."""
    interaction_id: UUID
    tool_name: Literal["orion.world.ownship.get"] = "orion.world.ownship.get"
    tool_version: Literal["1.0"] = "1.0"
    output_schema: Literal["orion.tool.output.ownship.v1"] = "orion.tool.output.ownship.v1"
    receipt: ToolReceipt
    fact_status: WorldFactStatus
    source: WorldFactSource
    authority: WorldFactAuthority
    observed_at: datetime | None
    age_seconds: float | None = Field(ge=0)
    generation: int | str | None
    aircraft_type: str | None = Field(max_length=160)
    expires_at: datetime


class InformationalResponsePlan(StrictModel):
    interaction_id: UUID
    language: Literal["ru-RU"] = "ru-RU"
    social_acts: tuple[SocialAct, ...] = Field(default=(), max_length=2)
    aircraft: AircraftIdentityQueryResult | None = None
    deadline: datetime

    @model_validator(mode="after")
    def shape(self):
        if not self.social_acts and self.aircraft is None:
            raise ValueError("empty_informational_plan")
        if len(set(self.social_acts)) != len(self.social_acts):
            raise ValueError("duplicate_social_act")
        if self.aircraft is not None and self.aircraft.interaction_id != self.interaction_id:
            raise ValueError("aircraft_interaction_mismatch")
        if self.deadline.tzinfo is None:
            raise ValueError("naive_informational_deadline")
        return self


class FinalizedInformationalText(StrictModel):
    plan: InformationalResponsePlan
    text: str = Field(min_length=1, max_length=1000, strict=True)
