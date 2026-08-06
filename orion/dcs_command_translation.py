from __future__ import annotations

from pydantic import BaseModel, Field

from orion.dcs_capabilities import (
    CapabilityDecision,
    CapabilityQuery,
    DcsRecipientType,
    dcs_capabilities,
)


class SemanticCommandRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)
    recipient_type: DcsRecipientType
    intent: str = Field(min_length=1, max_length=120)
    mission_bridge_available: bool = False
    target_available: bool = False
    recipient_id: str | None = Field(default=None, max_length=160)


class SemanticCommandPlan(BaseModel):
    transcript: str
    recipient_type: DcsRecipientType
    recipient_id: str | None = None
    intent: str
    decision: CapabilityDecision
    executable: bool
    requires_confirmation: bool
    confirmation_prompt: str | None = None
    command_payload: dict[str, str | bool | None] = Field(default_factory=dict)


def build_command_plan(request: SemanticCommandRequest) -> SemanticCommandPlan:
    decision = dcs_capabilities.decide(
        CapabilityQuery(
            recipient_type=request.recipient_type,
            intent=request.intent,
            mission_bridge_available=request.mission_bridge_available,
            target_available=request.target_available,
        )
    )
    confirmation_prompt = None
    if decision.supported and decision.requires_confirmation:
        recipient = request.recipient_id or request.recipient_type.value
        confirmation_prompt = f"Confirm command {decision.dcs_command or request.intent} for {recipient}"

    payload: dict[str, str | bool | None] = {
        "recipient_type": request.recipient_type.value,
        "recipient_id": request.recipient_id,
        "intent": request.intent,
        "channel": decision.channel.value if decision.channel else None,
        "dcs_command": decision.dcs_command,
        "requires_confirmation": decision.requires_confirmation,
    }
    return SemanticCommandPlan(
        transcript=request.transcript,
        recipient_type=request.recipient_type,
        recipient_id=request.recipient_id,
        intent=request.intent,
        decision=decision,
        executable=decision.supported,
        requires_confirmation=decision.requires_confirmation,
        confirmation_prompt=confirmation_prompt,
        command_payload=payload,
    )
