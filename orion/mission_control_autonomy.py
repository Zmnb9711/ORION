from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.jtac_assets import available_jtac_assets
from orion.mission_control_runtime import MissionControlReadiness, build_mission_control_picture


class MissionControlAction(StrEnum):
    OBSERVE = "observe"
    SUGGEST_JTAC = "suggest_jtac"
    SUGGEST_9LINE = "suggest_9line"


class MissionControlAutonomyDecision(BaseModel):
    action: MissionControlAction
    target_id: str | None = None
    target_name: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    requires_pilot_confirmation: bool = True
    available_designators: int = 0


def evaluate_mission_control_autonomy() -> MissionControlAutonomyDecision:
    picture = build_mission_control_picture()
    target = picture.primary_surface_threat
    if picture.readiness is MissionControlReadiness.UNAVAILABLE:
        return MissionControlAutonomyDecision(
            action=MissionControlAction.OBSERVE,
            confidence=0.0,
            reason="Tactical picture unavailable",
            requires_pilot_confirmation=False,
        )
    if target is None:
        return MissionControlAutonomyDecision(
            action=MissionControlAction.OBSERVE,
            confidence=0.25,
            reason="No prioritized surface threat",
            requires_pilot_confirmation=False,
        )

    assets = available_jtac_assets()
    laser_assets = [item for item in assets if item.supports_laser]
    if not laser_assets:
        return MissionControlAutonomyDecision(
            action=MissionControlAction.OBSERVE,
            target_id=target.unit_id,
            target_name=target.name,
            confidence=0.45,
            reason="Surface threat detected, but no laser-capable JTAC/designator is available",
            requires_pilot_confirmation=False,
        )

    # A primary SAM is a strong candidate for a structured CAS workflow because it
    # benefits from explicit target/location/restriction verification before tasking.
    is_sam = target.kind.value == "sam"
    return MissionControlAutonomyDecision(
        action=MissionControlAction.SUGGEST_9LINE if is_sam else MissionControlAction.SUGGEST_JTAC,
        target_id=target.unit_id,
        target_name=target.name,
        confidence=0.9 if is_sam else 0.75,
        reason="Prioritized surface threat with an available JTAC/designator",
        requires_pilot_confirmation=True,
        available_designators=len(laser_assets),
    )
