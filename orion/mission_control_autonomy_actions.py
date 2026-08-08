from __future__ import annotations

from pydantic import BaseModel, Field

from orion.confirmations import ConfirmationStatus, PendingAction, PendingActionCreate, confirmation_store
from orion.mission_control_autonomy import MissionControlAction, MissionControlAutonomyDecision
from orion.mission_control_jtac import MissionControlJtacRequest, MissionControlJtacResult, orchestrate_jtac
from orion.mission_store import mission_store


class Cas9LineSeed(BaseModel):
    target_id: str
    target_name: str
    target_description: str
    target_location: str
    target_elevation_ft: int
    distance_nm: float | None = None
    mark: str = "laser"
    laser_code: int = 1688
    missing_fields: list[str] = Field(default_factory=lambda: ["ip_or_bp", "heading_deg", "friendlies", "egress"])


class MissionControlAutonomyResolution(BaseModel):
    pending_action: PendingAction
    executed: bool = False
    jtac_result: MissionControlJtacResult | None = None
    cas_9line_seed: Cas9LineSeed | None = None


def create_autonomy_pending_action(decision: MissionControlAutonomyDecision) -> PendingAction:
    if not decision.requires_pilot_confirmation or decision.action is MissionControlAction.OBSERVE:
        raise ValueError("Autonomy decision does not require pilot confirmation")
    if not decision.target_id:
        raise ValueError("Autonomy decision has no target")
    summary = (
        f"Prepare 9-line CAS workflow for {decision.target_name or decision.target_id}"
        if decision.action is MissionControlAction.SUGGEST_9LINE
        else f"Request JTAC support for {decision.target_name or decision.target_id}"
    )
    return confirmation_store.create(
        PendingActionCreate(
            action_type=f"mission_control:{decision.action.value}",
            summary=summary,
            payload={
                "target_id": decision.target_id,
                "target_name": decision.target_name,
                "confidence": decision.confidence,
                "reason": decision.reason,
            },
        )
    )


def resolve_autonomy_pending_action(action_id: str, *, confirm: bool) -> MissionControlAutonomyResolution:
    resolved = confirmation_store.resolve(action_id, confirm)
    if resolved is None:
        raise KeyError("Pending Mission Control action not found or already resolved")
    if resolved.status is ConfirmationStatus.REJECTED:
        return MissionControlAutonomyResolution(pending_action=resolved)

    target_id = str(resolved.payload.get("target_id") or "")
    if not target_id:
        raise ValueError("Pending Mission Control action has no target")

    if resolved.action_type == "mission_control:suggest_jtac":
        jtac_result = orchestrate_jtac(MissionControlJtacRequest(target_id=target_id))
        return MissionControlAutonomyResolution(
            pending_action=resolved,
            executed=jtac_result.accepted,
            jtac_result=jtac_result,
        )

    if resolved.action_type == "mission_control:suggest_9line":
        unit = mission_store.unit(target_id)
        if unit is None or not unit.alive or not unit.detected:
            raise ValueError("Target is no longer available in the current mission picture")
        seed = Cas9LineSeed(
            target_id=unit.unit_id,
            target_name=unit.name,
            target_description=unit.type_name or unit.name,
            target_location=f"{unit.position.latitude:.6f}, {unit.position.longitude:.6f}",
            target_elevation_ft=round(unit.position.altitude_m * 3.28084),
        )
        return MissionControlAutonomyResolution(
            pending_action=resolved,
            executed=True,
            cas_9line_seed=seed,
        )

    raise ValueError(f"Unsupported Mission Control action: {resolved.action_type}")
