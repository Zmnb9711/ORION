from __future__ import annotations

from pydantic import BaseModel

from orion.confirmations import ConfirmationStatus, PendingAction, PendingActionCreate, confirmation_store
from orion.jtac_runtime import JtacDesignationMethod
from orion.mission_control_coordination import MissionControlAssignment, build_mission_control_coordination_plan
from orion.mission_control_jtac import MissionControlJtacRequest, MissionControlJtacResult, orchestrate_jtac
from orion.mission_store import mission_store


class MissionControlCoordinationResolution(BaseModel):
    pending_action: PendingAction
    executed: bool = False
    stale: bool = False
    jtac_result: MissionControlJtacResult | None = None


def create_coordination_pending_action(assignment: MissionControlAssignment) -> PendingAction:
    snapshot = mission_store.get()
    summary = f"Assign {assignment.designator_name} to {assignment.target_name} via {assignment.designation_method.value}"
    return confirmation_store.create(
        PendingActionCreate(
            action_type="mission_control:coordinate_designator",
            summary=summary,
            payload={
                "mission_id": snapshot.mission_id if snapshot is not None else None,
                "target_id": assignment.target_id,
                "target_name": assignment.target_name,
                "target_kind": assignment.target_kind.value,
                "tactical_priority": assignment.tactical_priority,
                "designator_id": assignment.designator_id,
                "designator_name": assignment.designator_name,
                "designation_method": assignment.designation_method.value,
            },
        )
    )


def _matching_current_assignment(pending: PendingAction) -> MissionControlAssignment | None:
    snapshot = mission_store.get()
    mission_id = pending.payload.get("mission_id")
    if snapshot is None or (mission_id is not None and snapshot.mission_id != mission_id):
        return None
    target_id = str(pending.payload.get("target_id") or "")
    designator_id = str(pending.payload.get("designator_id") or "")
    method = str(pending.payload.get("designation_method") or "")
    plan = build_mission_control_coordination_plan()
    return next(
        (
            assignment
            for assignment in plan.assignments
            if assignment.target_id == target_id
            and assignment.designator_id == designator_id
            and assignment.designation_method.value == method
        ),
        None,
    )


def resolve_coordination_pending_action(
    action_id: str,
    *,
    confirm: bool,
    language: str = "en",
) -> MissionControlCoordinationResolution:
    pending = confirmation_store.get(action_id)
    if pending is None or pending.status is not ConfirmationStatus.PENDING:
        raise KeyError("Pending Mission Control coordination action not found or already resolved")
    if pending.action_type != "mission_control:coordinate_designator":
        raise ValueError("Pending action is not a Mission Control coordination assignment")

    if not confirm:
        resolved = confirmation_store.resolve(action_id, False)
        if resolved is None:
            raise KeyError("Pending Mission Control coordination action not found or already resolved")
        return MissionControlCoordinationResolution(pending_action=resolved)

    assignment = _matching_current_assignment(pending)
    if assignment is None:
        rejected = confirmation_store.resolve(action_id, False)
        if rejected is None:
            raise KeyError("Pending Mission Control coordination action not found or already resolved")
        return MissionControlCoordinationResolution(pending_action=rejected, stale=True)

    resolved = confirmation_store.resolve(action_id, True)
    if resolved is None:
        raise KeyError("Pending Mission Control coordination action not found or already resolved")

    method = JtacDesignationMethod(str(resolved.payload["designation_method"]))
    jtac_result = orchestrate_jtac(
        MissionControlJtacRequest(
            target_id=str(resolved.payload["target_id"]),
            requested_asset_id=str(resolved.payload["designator_id"]),
            method=method,
            laser_code=1688 if method is JtacDesignationMethod.LASER else None,
            language=language,
        )
    )
    return MissionControlCoordinationResolution(
        pending_action=resolved,
        executed=jtac_result.accepted,
        jtac_result=jtac_result,
    )
