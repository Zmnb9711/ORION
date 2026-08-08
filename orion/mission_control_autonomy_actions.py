from __future__ import annotations

from pydantic import BaseModel, Field

from orion.cas_9line import Cas9LineBrief, Cas9LineBriefCreate, cas_9line_store
from orion.confirmations import ConfirmationStatus, PendingAction, PendingActionCreate, confirmation_store
from orion.jtac_runtime import JtacDesignationMethod
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
    designator_id: str | None = None
    designator_name: str | None = None
    missing_fields: list[str] = Field(
        default_factory=lambda: [
            "ip_or_bp",
            "heading_deg",
            "distance_nm",
            "friendlies",
            "egress",
            "restrictions",
            "remarks",
        ]
    )


class Cas9LineAutonomyCompletion(BaseModel):
    ip_or_bp: str = Field(min_length=1)
    heading_deg: int = Field(ge=0, le=359)
    distance_nm: float = Field(gt=0)
    friendlies: str = Field(min_length=1)
    egress: str = Field(min_length=1)
    restrictions: str | None = None
    remarks: str | None = None
    language: str = "en"


class MissionControlAutonomyResolution(BaseModel):
    pending_action: PendingAction
    executed: bool = False
    jtac_result: MissionControlJtacResult | None = None
    cas_9line_seed: Cas9LineSeed | None = None
    stale: bool = False
    current_decision: MissionControlAutonomyDecision | None = None
    replacement_action: PendingAction | None = None


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
                "designator_id": decision.selected_designator_id,
                "designator_name": decision.selected_designator_name,
                "designator_supports_laser": decision.selected_designator_supports_laser,
                "designator_supports_smoke": decision.selected_designator_supports_smoke,
                "designation_method": decision.selected_designation_method.value if decision.selected_designation_method else None,
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


def _revalidate_decision(resolved: PendingAction) -> MissionControlAutonomyDecision:
    current = evaluate_mission_control_autonomy()
    expected_type = f"mission_control:{current.action.value}"
    target_id = str(resolved.payload.get("target_id") or "")
    designator_id = resolved.payload.get("designator_id")
    designation_method = resolved.payload.get("designation_method")
    current_method = current.selected_designation_method.value if current.selected_designation_method else None
    if (
        not current.requires_pilot_confirmation
        or current.target_id != target_id
        or expected_type != resolved.action_type
        or (designator_id is not None and current.selected_designator_id != designator_id)
        or (designation_method is not None and current_method != designation_method)
    ):
        raise ValueError("Tactical recommendation changed since proposal creation; proposal is stale")
    return current


def _replace_stale_action(pending: PendingAction) -> MissionControlAutonomyResolution:
    rejected = confirmation_store.resolve(pending.action_id, False)
    if rejected is None:
        raise KeyError("Pending Mission Control action not found or already resolved")
    current = evaluate_mission_control_autonomy()
    replacement = None
    if current.requires_pilot_confirmation and current.action is not MissionControlAction.OBSERVE:
        replacement = create_autonomy_pending_action(current)
    return MissionControlAutonomyResolution(
        pending_action=rejected,
        stale=True,
        current_decision=current,
        replacement_action=replacement,
    )


def _build_9line_seed(unit, current: MissionControlAutonomyDecision) -> Cas9LineSeed:
    return Cas9LineSeed(
        target_id=unit.unit_id,
        target_name=unit.name,
        target_description=unit.type_name or unit.name,
        target_location=f"{unit.position.latitude:.6f}, {unit.position.longitude:.6f}",
        target_elevation_ft=round(unit.position.altitude_m * 3.28084),
        mark="laser",
        laser_code=1688,
        designator_id=current.selected_designator_id,
        designator_name=current.selected_designator_name,
    )


def resolve_autonomy_pending_action(action_id: str, *, confirm: bool) -> MissionControlAutonomyResolution:
    pending = confirmation_store.get(action_id)
    if pending is None or pending.status is not ConfirmationStatus.PENDING:
        raise KeyError("Pending Mission Control action not found or already resolved")
    if not confirm:
        resolved = confirmation_store.resolve(action_id, False)
        if resolved is None:
            raise KeyError("Pending Mission Control action not found or already resolved")
        return MissionControlAutonomyResolution(pending_action=resolved)

    try:
        unit = _current_target(pending)
        current = _revalidate_decision(pending)
    except ValueError:
        return _replace_stale_action(pending)

    resolved = confirmation_store.resolve(action_id, True)
    if resolved is None:
        raise KeyError("Pending Mission Control action not found or already resolved")

    target_id = unit.unit_id
    if resolved.action_type == "mission_control:suggest_jtac":
        method = current.selected_designation_method or JtacDesignationMethod.LASER
        jtac_result = orchestrate_jtac(
            MissionControlJtacRequest(
                target_id=target_id,
                requested_asset_id=current.selected_designator_id,
                method=method,
                laser_code=1688 if method is JtacDesignationMethod.LASER else None,
            )
        )
        return MissionControlAutonomyResolution(
            pending_action=resolved,
            executed=jtac_result.accepted,
            jtac_result=jtac_result,
        )

    if resolved.action_type == "mission_control:suggest_9line":
        return MissionControlAutonomyResolution(
            pending_action=resolved,
            cas_9line_seed=_build_9line_seed(unit, current),
        )

    raise ValueError(f"Unsupported Mission Control action: {resolved.action_type}")


def complete_autonomy_9line(action_id: str, payload: Cas9LineAutonomyCompletion) -> Cas9LineBrief:
    action = confirmation_store.get(action_id)
    if action is None:
        raise KeyError("Mission Control action not found")
    if action.status is not ConfirmationStatus.CONFIRMED or action.action_type != "mission_control:suggest_9line":
        raise ValueError("Mission Control action is not a confirmed 9-line proposal")

    unit = _current_target(action)
    current = _revalidate_decision(action)
    if current.action is not MissionControlAction.SUGGEST_9LINE:
        raise ValueError("Tactical recommendation changed since proposal creation; proposal is stale")
    if current.selected_designation_method not in {None, JtacDesignationMethod.LASER}:
        raise ValueError("Confirmed 9-line proposal no longer has a laser-capable designator")

    seed = _build_9line_seed(unit, current)
    return cas_9line_store.create(
        Cas9LineBriefCreate(
            target_id=seed.target_id,
            ip_or_bp=payload.ip_or_bp,
            heading_deg=payload.heading_deg,
            distance_nm=payload.distance_nm,
            target_elevation_ft=seed.target_elevation_ft,
            target_description=seed.target_description,
            target_location=seed.target_location,
            mark=f"laser {seed.laser_code}",
            friendlies=payload.friendlies,
            egress=payload.egress,
            remarks=payload.remarks,
            restrictions=payload.restrictions,
            method=JtacDesignationMethod.LASER,
            laser_code=seed.laser_code,
            requested_asset_id=seed.designator_id,
            source_action_id=action.action_id,
            language=payload.language,
        )
    )
