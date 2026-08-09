from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import RLock

from pydantic import BaseModel

from orion.confirmations import ConfirmationStatus, PendingAction, confirmation_store
from orion.mission import MissionSnapshot
from orion.mission_control_autonomy import MissionControlAction, MissionControlAutonomyDecision, evaluate_mission_control_autonomy
from orion.mission_control_autonomy_actions import create_autonomy_pending_action
from orion.mission_control_autonomy_voice import submit_autonomy_proposal_voice


class ProactiveMissionControlResult(BaseModel):
    decision: MissionControlAutonomyDecision | None = None
    proposal: PendingAction | None = None
    replaced_action_id: str | None = None
    cancelled_action_id: str | None = None
    suppressed: bool = False
    suppression_reason: str | None = None


class ProactiveMissionControlRuntime:
    def __init__(
        self,
        *,
        cooldown_seconds: float = 30.0,
        deescalation_observations: int = 2,
        replacement_observations: int = 2,
        confidence_escalation_delta: float = 0.15,
    ) -> None:
        self._lock = RLock()
        self._enabled = False
        self._mission_id: str | None = None
        self._active_action_id: str | None = None
        self._last_signature: tuple[str, str, str, str] | None = None
        self._last_announced_at: datetime | None = None
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._deescalation_observations = max(1, deescalation_observations)
        self._replacement_observations = max(1, replacement_observations)
        self._confidence_escalation_delta = max(0.0, confidence_escalation_delta)
        self._deescalation_count = 0
        self._candidate_signature: tuple[str, str, str, str] | None = None
        self._candidate_count = 0

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._reset_state()

    def observe(
        self,
        snapshot: MissionSnapshot,
        *,
        now: datetime | None = None,
        language: str = "en",
    ) -> ProactiveMissionControlResult:
        now = now or datetime.now(UTC)
        with self._lock:
            if not self._enabled:
                return ProactiveMissionControlResult(suppressed=True, suppression_reason="runtime disabled")

            if snapshot.mission_id != self._mission_id:
                self._reset_state()
                self._mission_id = snapshot.mission_id

            decision = evaluate_mission_control_autonomy()
            active = self._active_pending()

            if decision.action is MissionControlAction.OBSERVE or not decision.requires_pilot_confirmation:
                self._reset_candidate()
                if active is None:
                    self._deescalation_count = 0
                    return ProactiveMissionControlResult(decision=decision)
                self._deescalation_count += 1
                if self._deescalation_count < self._deescalation_observations:
                    return ProactiveMissionControlResult(
                        decision=decision,
                        proposal=active,
                        suppressed=True,
                        suppression_reason="de-escalation hysteresis active",
                    )
                cancelled = self._reject(active)
                self._active_action_id = None
                self._deescalation_count = 0
                return ProactiveMissionControlResult(decision=decision, cancelled_action_id=cancelled)

            self._deescalation_count = 0
            signature = self._signature(decision)
            if active is not None:
                if self._action_matches_decision(active, decision):
                    self._reset_candidate()
                    return ProactiveMissionControlResult(
                        decision=decision,
                        proposal=active,
                        suppressed=True,
                        suppression_reason="matching proposal already pending",
                    )

                if self._is_escalation(active, decision):
                    self._reset_candidate()
                    replaced = self._reject(active)
                    proposal = self._create(decision, now=now, language=language)
                    return ProactiveMissionControlResult(
                        decision=decision,
                        proposal=proposal,
                        replaced_action_id=replaced,
                    )

                if self._candidate_signature == signature:
                    self._candidate_count += 1
                else:
                    self._candidate_signature = signature
                    self._candidate_count = 1
                if self._candidate_count < self._replacement_observations:
                    return ProactiveMissionControlResult(
                        decision=decision,
                        proposal=active,
                        suppressed=True,
                        suppression_reason="replacement hysteresis active",
                    )

                self._reset_candidate()
                replaced = self._reject(active)
                proposal = self._create(decision, now=now, language=language)
                return ProactiveMissionControlResult(
                    decision=decision,
                    proposal=proposal,
                    replaced_action_id=replaced,
                )

            self._reset_candidate()
            if self._last_signature == signature and self._last_announced_at is not None:
                if now - self._last_announced_at < self._cooldown:
                    return ProactiveMissionControlResult(
                        decision=decision,
                        suppressed=True,
                        suppression_reason="proposal cooldown active",
                    )

            proposal = self._create(decision, now=now, language=language)
            return ProactiveMissionControlResult(decision=decision, proposal=proposal)

    def reset(self) -> None:
        with self._lock:
            self._reset_state()

    def _reset_state(self) -> None:
        self._mission_id = None
        self._active_action_id = None
        self._last_signature = None
        self._last_announced_at = None
        self._deescalation_count = 0
        self._reset_candidate()

    def _reset_candidate(self) -> None:
        self._candidate_signature = None
        self._candidate_count = 0

    def _active_pending(self) -> PendingAction | None:
        if self._active_action_id is None:
            return None
        item = confirmation_store.get(self._active_action_id)
        if item is None or item.status is not ConfirmationStatus.PENDING:
            self._active_action_id = None
            return None
        return item

    def _create(self, decision: MissionControlAutonomyDecision, *, now: datetime, language: str) -> PendingAction:
        proposal = create_autonomy_pending_action(decision)
        submit_autonomy_proposal_voice(proposal, language=language)
        self._active_action_id = proposal.action_id
        self._last_signature = self._signature(decision)
        self._last_announced_at = now
        return proposal

    @staticmethod
    def _reject(action: PendingAction | None) -> str | None:
        if action is None:
            return None
        resolved = confirmation_store.resolve(action.action_id, False)
        return resolved.action_id if resolved is not None else None

    def _is_escalation(self, active: PendingAction, decision: MissionControlAutonomyDecision) -> bool:
        active_action = active.action_type.removeprefix("mission_control:")
        active_rank = self._action_rank(active_action)
        current_rank = self._action_rank(decision.action.value)
        if current_rank > active_rank:
            return True
        active_confidence = float(active.payload.get("confidence") or 0.0)
        return decision.confidence >= active_confidence + self._confidence_escalation_delta

    @staticmethod
    def _action_rank(action: str) -> int:
        return {
            MissionControlAction.OBSERVE.value: 0,
            MissionControlAction.SUGGEST_JTAC.value: 1,
            MissionControlAction.SUGGEST_9LINE.value: 2,
        }.get(action, 0)

    @staticmethod
    def _signature(decision: MissionControlAutonomyDecision) -> tuple[str, str, str, str]:
        return (
            decision.action.value,
            decision.target_id or "",
            decision.selected_designator_id or "",
            decision.selected_designation_method.value if decision.selected_designation_method else "",
        )

    @staticmethod
    def _action_matches_decision(action: PendingAction, decision: MissionControlAutonomyDecision) -> bool:
        return (
            action.action_type == f"mission_control:{decision.action.value}"
            and action.payload.get("target_id") == decision.target_id
            and action.payload.get("designator_id") == decision.selected_designator_id
            and action.payload.get("designation_method")
            == (decision.selected_designation_method.value if decision.selected_designation_method else None)
        )


proactive_mission_control = ProactiveMissionControlRuntime()


def observe_snapshot_for_proactive_mission_control(snapshot: MissionSnapshot) -> ProactiveMissionControlResult:
    return proactive_mission_control.observe(snapshot)
