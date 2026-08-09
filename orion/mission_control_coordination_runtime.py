from __future__ import annotations

from threading import RLock

from pydantic import BaseModel, Field

from orion.confirmations import ConfirmationStatus, PendingAction, confirmation_store
from orion.mission import MissionSnapshot
from orion.mission_control_coordination import MissionControlAssignment, build_mission_control_coordination_plan
from orion.mission_control_coordination_actions import create_coordination_pending_action
from orion.orion_settings import CommunicationMode, orion_settings
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommandCreate, voice_commands


class MissionControlCoordinationRuntimeStatus(BaseModel):
    enabled: bool
    mission_id: str | None = None
    active_action_ids: list[str] = Field(default_factory=list)
    active_target_ids: list[str] = Field(default_factory=list)
    max_active_proposals: int = 0
    language: str = "en"
    last_announced_signature: str | None = None


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
        self._last_announced_signature: str | None = None

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._cancel_all()
            self._enabled = False
            self._mission_id = None
            self._last_announced_signature = None

    def reset(self) -> None:
        with self._lock:
            self._cancel_all()
            self._mission_id = None
            self._last_announced_signature = None

    def status(self) -> MissionControlCoordinationRuntimeStatus:
        with self._lock:
            active = self._active_pending()
            return MissionControlCoordinationRuntimeStatus(
                enabled=self._enabled,
                mission_id=self._mission_id,
                active_action_ids=[item.action_id for item in active.values()],
                active_target_ids=list(active),
                max_active_proposals=self._max_active_proposals,
                language=self._resolve_language(),
                last_announced_signature=self._last_announced_signature,
            )

    def observe(self, snapshot: MissionSnapshot) -> MissionControlCoordinationRuntimeResult:
        with self._lock:
            if not self._enabled:
                return MissionControlCoordinationRuntimeResult(suppressed=True, suppression_reason="runtime disabled")

            if snapshot.mission_id != self._mission_id:
                self._cancel_all()
                self._mission_id = snapshot.mission_id
                self._last_announced_signature = None

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
                pending = create_coordination_pending_action(assignment)
                self._active_by_target[target_id] = pending.action_id
                result.created.append(pending)

            self._announce_if_changed(result)
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

    def _announce_if_changed(self, result: MissionControlCoordinationRuntimeResult) -> None:
        if not result.created and not result.cancelled_action_ids:
            return
        active = self._active_pending()
        signature = "|".join(
            sorted(
                f"{target}:{item.payload.get('designator_id')}:{item.payload.get('designation_method')}"
                for target, item in active.items()
            )
        )
        if signature == self._last_announced_signature:
            return
        self._last_announced_signature = signature
        language = self._resolve_language()
        ru = language.startswith("ru")
        created = len(result.created)
        cancelled = len(result.cancelled_action_ids)
        if created and cancelled:
            text = (
                f"План целеуказания обновлён: новых назначений {created}, отменено {cancelled}."
                if ru
                else f"Designation plan updated: {created} new assignment(s), {cancelled} cancelled."
            )
        elif created:
            text = (
                f"План целеуказания обновлён. Новых назначений: {created}."
                if ru
                else f"Designation plan updated. {created} new assignment(s)."
            )
        else:
            text = (
                f"План целеуказания обновлён. Отменено назначений: {cancelled}."
                if ru
                else f"Designation plan updated. {cancelled} assignment(s) cancelled."
            )
        voice_commands.submit(
            VoiceCommandCreate(
                transcript=text,
                intent="mission_control_coordination_update",
                agent=VoiceAgent.MISSION_CONTROL,
                priority=CommandPriority.HIGH,
                context={
                    "mission_id": self._mission_id or "",
                    "created": created,
                    "cancelled": cancelled,
                    "active_targets": ",".join(sorted(active)),
                    "unassigned_targets": ",".join(result.unassigned_target_ids),
                    "language": language,
                },
            )
        )

    @staticmethod
    def _resolve_language() -> str:
        settings = orion_settings.get()
        if settings.communication_mode is CommunicationMode.AVIATION_RUSSIAN:
            return "ru"
        if settings.communication_mode is CommunicationMode.AVIATION_ENGLISH:
            return "en"
        return settings.interface_language.value

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


coordination_mission_control = MissionControlCoordinationRuntime()


def observe_snapshot_for_coordination_mission_control(snapshot: MissionSnapshot) -> MissionControlCoordinationRuntimeResult:
    # Follow the established proactive Mission Control application lifecycle without
    # introducing another global startup dependency in app.py.
    from orion.mission_control_proactive import proactive_mission_control

    if proactive_mission_control.enabled:
        if not coordination_mission_control.enabled:
            coordination_mission_control.enable()
    elif coordination_mission_control.enabled:
        coordination_mission_control.disable()
    return coordination_mission_control.observe(snapshot)
