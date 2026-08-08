from __future__ import annotations

from pydantic import BaseModel, Field

from orion.confirmations import ConfirmationStatus, PendingAction, PendingActionCreate, confirmation_store
from orion.mission_control_autonomy import MissionControlAction, MissionControlAutonomyDecision, evaluate_mission_control_autonomy
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
    snapshot = mission_store.get()
    return confirmation_store.create(
        PendingActionCreate(
            action_type=f"mission_control:{decision.action.value}",
            summary=summary,
            payload={
                "target_id": decision.target_id,
                "target_name": decision.target_name,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "mission_id": snapshot.mission_id if snapshot is not None else None,
            },
        )
    )


def _current_target(resolved: PendingAction):
    target_id = str(resolved.payload.get("target_id") or "")
    if not target_id:
        raise ValueError("Pending Mission Control action has no target")
    snapshot = mission_store.get()
    if snapshot is None:
        raise ValueError("Mission picture is no longer available; proposal is stale")
    mission_id = resolved.payload.get("mission_id")
    if mission_id is not None and snapshot.mission_id != mission_id:
        raise ValueError("Mission changed since proposal creation; proposal is stale")
    unit = next((item for item in snapshot.units if item.unit_id == target_id), None)
    if unit is None or not unit.alive or not unit.detected:
        raise ValueError("Target is no longer available in the current mission picture; proposal is stale")
    return unit


def _revalidate_decision(resolved: PendingAction) -> None:
    current = evaluate_mission_control_autonomy()
    expected_type = f"mission_control:{current.action.value}"
    target_id = str(resolved.payload.get("target_id") or "")
    if (
        not current.requires_pilot_confirmation
        or current.target_id != target_id
        or expected_type != resolved.action_type
    ):
        raise ValueError("Tactical recommendation changed since proposal creation; proposal is stale")


def resolve_autonomy_pending_action(action_id: str, *, confirm: bool) -> MissionControlAutonomyResolution:
    pending = confirmation_store.get(action_id)
    if pending is None or pending.status is not ConfirmationStatus.PENDING:
        raise KeyError("Pending Mission Control action not found or already resolved")
    if not confirm:
        resolved = confirmation_store.resolve(action_id, False)
        if resolved is None:
            raise KeyError("Pending Mission Control action not found or already resolved")
        return MissionControlAutonomyResolution(pending_action=resolved)

    # Revalidate both mission identity/target existence and the current decision before
    # consuming confirmation. A changed tactical recommendation must not execute old intent.
    unit = _current_target(pending)
    _revalidate_decision(pending)
    resolved = confirmation_store.resolve(action_id, True)
    if resolved is None:
        raise KeyError("Pending Mission Control action not found or already resolved")

    target_id = unit.unit_id
    if resolved.action_type == "mission_control:suggest_jtac":
        jtac_result = orchestrate_jtac(MissionControlJtacRequest(target_id=target_id))
        return MissionControlAutonomyResolution(
            pending_action=resolved,
            executed=jtac_result.accepted,
            jtac_result=jtac_result,
        )

    if resolved.action_type == "mission_control:suggest_9line":
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
