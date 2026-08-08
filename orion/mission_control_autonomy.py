from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.jtac_assets import JtacAsset, available_jtac_assets
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
    selected_designator_id: str | None = None
    selected_designator_name: str | None = None
    selected_designator_supports_laser: bool = False
    selected_designator_supports_smoke: bool = False


def _select_designator(assets: list[JtacAsset]) -> JtacAsset | None:
    capable = [item for item in assets if item.supports_laser or item.supports_smoke]
    if not capable:
        return None
    capable.sort(
        key=lambda item: (
            not item.explicit_fac_role,
            not item.supports_laser,
            not item.supports_smoke,
            item.name.casefold(),
        )
    )
    return capable[0]


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
    designators = [item for item in assets if item.supports_laser or item.supports_smoke]
    selected = _select_designator(assets)
    if selected is None:
        return MissionControlAutonomyDecision(
            action=MissionControlAction.OBSERVE,
            target_id=target.unit_id,
            target_name=target.name,
            confidence=0.45,
            reason="Surface threat detected, but no JTAC/designator with laser or smoke capability is available",
            requires_pilot_confirmation=False,
        )

    is_sam = target.kind.value == "sam"
    # A structured 9-line proposal currently requires a laser-capable designator.
    # Smoke-only FAC support is still useful, but routes through the generic JTAC workflow.
    action = MissionControlAction.SUGGEST_9LINE if is_sam and selected.supports_laser else MissionControlAction.SUGGEST_JTAC
    return MissionControlAutonomyDecision(
        action=action,
        target_id=target.unit_id,
        target_name=target.name,
        confidence=0.9 if action is MissionControlAction.SUGGEST_9LINE else 0.75,
        reason="Prioritized surface threat with an available JTAC/designator",
        requires_pilot_confirmation=True,
        available_designators=len(designators),
        selected_designator_id=selected.unit_id,
        selected_designator_name=selected.name,
        selected_designator_supports_laser=selected.supports_laser,
        selected_designator_supports_smoke=selected.supports_smoke,
    )
