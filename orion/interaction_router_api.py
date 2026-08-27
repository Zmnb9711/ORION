"""Core HTTP boundary for the narrow IA-6 production interaction slice."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationProfileId,
)
from orion.interaction_contracts import InteractionRequest
from orion.interaction_router import InteractionRouter, InteractionRouterExecution
from orion.planner import PlannerProvider
from orion.yandex_qwen_planner import (
    YandexQwenPlannerProvider,
    load_yandex_qwen_planner_config,
)


router = APIRouter(prefix="/v1/interactions", tags=["Interaction Router"])


def _runtime_dir() -> Path:
    configured = os.environ.get("ORION_RUNTIME_DIR")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else (Path.cwd() / "runtime")
    )


def _production_provider() -> PlannerProvider:
    return YandexQwenPlannerProvider(load_yandex_qwen_planner_config(_runtime_dir()))


interaction_router = InteractionRouter(provider_factory=_production_provider)


class InteractionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction_id: UUID = Field(default_factory=uuid4)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    turn_id: str | None = Field(default=None, min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=4_000, repr=False)
    communication_profile: CommunicationProfileId = CommunicationProfileId.ICAO
    domain: CommunicationDomain = CommunicationDomain.GENERAL
    input_language: str | None = Field(default=None, min_length=2, max_length=35)
    timeout_seconds: float = Field(default=45, ge=1, le=60)


@router.post("", response_model=InteractionRouterExecution)
def execute_interaction(payload: InteractionSubmission) -> InteractionRouterExecution:
    now = datetime.now(UTC)
    request = InteractionRequest(
        interaction_id=payload.interaction_id,
        session_id=payload.session_id,
        turn_id=payload.turn_id,
        text=payload.text,
        role_hint="pilot",
        domain_hint=payload.domain.value,
        created_at=now,
    )
    communication = CommunicationContext(
        profile_id=payload.communication_profile,
        domain=payload.domain,
        input_language=payload.input_language,
    )
    return interaction_router.execute(
        request,
        communication,
        deadline=now + timedelta(seconds=payload.timeout_seconds),
    )
