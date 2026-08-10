from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalState
from orion.airport_surface import RunwayAvailability
from orion.atc_operations import FreshnessClass


class ArrivalSafetyAction(StrEnum):
    CONTINUE = "continue"
    WITHHOLD_LANDING_CLEARANCE = "withhold_landing_clearance"
    GO_AROUND = "go_around"


class ArrivalSafetyDecision(BaseModel):
    action: ArrivalSafetyAction
    reason: str


class AirportArrivalSafetyController:
    """Turns observed runway state into explicit arrival safety decisions."""

    def __init__(self, runtime: AirportArrivalRuntime) -> None:
        self.runtime = runtime

    def evaluate(self, session_id: UUID) -> ArrivalSafetyDecision:
        session = self.runtime.get(session_id)
        if session is None:
            raise KeyError("Airport arrival session not found")
        runway = self.runtime.surface.runways.get(session.runway_id)
        if runway is None:
            return ArrivalSafetyDecision(
                action=self._unsafe_action(session.state),
                reason="runway state unavailable",
            )
        if runway.freshness in {FreshnessClass.STALE, FreshnessClass.UNKNOWN}:
            return ArrivalSafetyDecision(
                action=self._unsafe_action(session.state),
                reason=f"runway state is {runway.freshness.value}",
            )
        if runway.availability is not RunwayAvailability.CLEAR:
            return ArrivalSafetyDecision(
                action=self._unsafe_action(session.state),
                reason=f"runway is {runway.availability.value}",
            )
        return ArrivalSafetyDecision(action=ArrivalSafetyAction.CONTINUE, reason="runway confirmed clear")

    def enforce(self, session_id: UUID, *, reason: str | None = None) -> ArrivalSafetyDecision:
        decision = self.evaluate(session_id)
        if decision.action is ArrivalSafetyAction.GO_AROUND:
            self.runtime.go_around(session_id, reason=reason or decision.reason)
        self.runtime.core.history.record(
            session_id=session_id,
            event_type="airport_arrival_safety_decision",
            reason=reason or decision.reason,
            details={"action": decision.action.value},
        )
        return decision

    @staticmethod
    def _unsafe_action(state: AirportArrivalState) -> ArrivalSafetyAction:
        if state is AirportArrivalState.LANDING_CLEARED:
            return ArrivalSafetyAction.GO_AROUND
        return ArrivalSafetyAction.WITHHOLD_LANDING_CLEARANCE
