from __future__ import annotations

from threading import RLock

from pydantic import BaseModel, Field

from orion.confirmations import ConfirmationStatus, PendingAction, confirmation_store
from orion.mission import MissionSnapshot
from orion.mission_control_autonomy import MissionControlAction, MissionControlAutonomyDecision
from orion.mission_control_autonomy_actions import create_autonomy_pending_action
from orion.mission_control_coordination import MissionControlAssignment, build_mission_control_coordination_plan


class MissionControlCoordinationRuntimeStatus(BaseModel):
    enabled: bool
    mission_id: str | None = None
    active_action_ids: list[str] = Field(default_factory=list)
    active_target_ids: list[str] = Field(default_factory=list)
    max_active_proposals: int = 0


class MissionControlCoordinationRuntimeResult(BaseModel):
    created: list[PendingAction] = Field(default_factory=list)
    retained_action_ids: list[str] = Field(default_factory=list)
    cancelled_action_ids: list[str] = Field(default_factory=list)
    unassigned_target_ids: list[str] = Field(default_factory=list)
    suppressed: bool = False
    suppression_reason: str | None = None


class MissionControlCoordinationRuntime:
    def __init__(self, *, max_active_proposals: int = 3) -> None:
        self._lock = RLock()
        self._enabled = False
        self._mission_id: str | None = None
        self._active_by_target: dict[str, str] = {}
        self._max_active_proposals = max(1, max_active_proposals)

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._cancel_all()
            self._enabled = False
            self._mission_id = None

    def reset(self) -> None:
        with self._lock:
            self._cancel_all()
            self._mission_id = None

    def status(self) -> MissionControlCoordinationRuntimeStatus:
        with self._lock:
            active = self._active_pending()
            return MissionControlCoordinationRuntimeStatus(
                enabled=self._enabled,
                mission_id=self._mission_id,
                active_action_ids=[item.action_id for item in active.values()],
                active_target_ids=list(active),
                max_active_proposals=self._max_active_proposals,
            )

    def observe(self, snapshot: MissionSnapshot) -> MissionControlCoordinationRuntimeResult:
        with self._lock:
            if not self._enabled:
                return MissionControlCoordinationRuntimeResult(suppressed=True, suppression_reason="runtime disabled")

            if snapshot.mission_id != self._mission_id:
                self._cancel_all()
                self._mission_id = snapshot.mission_id

            plan = build_mission_control_coordination_plan(limit=self._max_active_proposals + 2)
            desired = {assignment.target_id: assignment for assignment in plan.assignments[: self._max_active_proposals]}
            active = self._active_pending()
            result = MissionControlCoordinationRuntimeResult(unassigned_target_ids=plan.unassigned_target_ids)

            for target_id, pending in list(active.items()):
                assignment = desired.get(target_id)
                if assignment is None or not self._matches(pending, assignment):
                    if self._reject(pending):
                        result.cancelled_action_ids.append(pending.action_id)
                    self._active_by_target.pop(target_id, None)
                else:
                    result.retained_action_ids.append(pending.action_id)

            for target_id, assignment in desired.items():
                if target_id in self._active_by_target:
                    continue
                pending = create_autonomy_pending_action(self._decision(assignment))
                self._active_by_target[target_id] = pending.action_id
                result.created.append(pending)

            return result

    def _active_pending(self) -> dict[str, PendingAction]:
        active: dict[str, PendingAction] = {}
        for target_id, action_id in list(self._active_by_target.items()):
            item = confirmation_store.get(action_id)
            if item is None or item.status is not ConfirmationStatus.PENDING:
                self._active_by_target.pop(target_id, None)
                continue
            active[target_id] = item
        return active

    def _cancel_all(self) -> None:
        for pending in self._active_pending().values():
            self._reject(pending)
        self._active_by_target.clear()

    @staticmethod
    def _reject(pending: PendingAction) -> bool:
        return confirmation_store.resolve(pending.action_id, False) is not None

    @staticmethod
    def _matches(pending: PendingAction, assignment: MissionControlAssignment) -> bool:
        return (
            pending.payload.get("target_id") == assignment.target_id
            and pending.payload.get("designator_id") == assignment.designator_id
            and pending.payload.get("designation_method") == assignment.designation_method.value
        )

    @staticmethod
    def _decision(assignment: MissionControlAssignment) -> MissionControlAutonomyDecision:
        action = (
            MissionControlAction.SUGGEST_9LINE
            if assignment.target_kind.value == "sam" and assignment.designation_method.value == "laser"
            else MissionControlAction.SUGGEST_JTAC
        )
        return MissionControlAutonomyDecision(
            action=action,
            target_id=assignment.target_id,
            target_name=assignment.target_name,
            confidence=0.9 if action is MissionControlAction.SUGGEST_9LINE else 0.75,
            reason="Coordinated multi-threat assignment with an available JTAC/designator",
            requires_pilot_confirmation=True,
            selected_designator_id=assignment.designator_id,
            selected_designator_name=assignment.designator_name,
            selected_designator_supports_laser=assignment.supports_laser,
            selected_designator_supports_smoke=assignment.supports_smoke,
            selected_designation_method=assignment.designation_method,
        )


coordination_mission_control = MissionControlCoordinationRuntime()
