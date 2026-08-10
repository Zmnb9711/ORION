from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalState, ApproachType
from orion.atc_core import ControllerAgency


class RunwaySightAction(StrEnum):
    CONTINUE = "continue"
    CONTINUE_VISUAL = "continue_visual"
    REPOSITION_OR_INSTRUMENT = "reposition_or_instrument"
    GO_AROUND = "go_around"


class RunwaySightReport(BaseModel):
    runway_in_sight: bool
    action: RunwaySightAction
    reason: str


class AirportArrivalReportController:
    """Maps pilot runway-sight reports to safe, state-aware arrival actions."""

    _REPORTABLE_STATES = {
        AirportArrivalState.APPROACH_CONTROL,
        AirportArrivalState.APPROACH_POSITIONING,
        AirportArrivalState.APPROACH,
        AirportArrivalState.FINAL,
        AirportArrivalState.TOWER,
        AirportArrivalState.LANDING_CLEARED,
    }

    def __init__(self, runtime: AirportArrivalRuntime) -> None:
        self.runtime = runtime

    def report_runway_in_sight(self, session_id: UUID, *, reason: str = "pilot reports runway in sight") -> RunwaySightReport:
        session = self._require_reportable(session_id)
        action = (
            RunwaySightAction.CONTINUE_VISUAL
            if session.clearance is not None and session.clearance.approach_type is ApproachType.VISUAL
            else RunwaySightAction.CONTINUE
        )
        report = RunwaySightReport(runway_in_sight=True, action=action, reason=reason)
        self._record(session_id, report, source_agency=self._source_agency(session.state))
        return report

    def report_runway_not_in_sight(
        self,
        session_id: UUID,
        *,
        reason: str = "pilot reports runway not in sight",
    ) -> RunwaySightReport:
        session = self._require_reportable(session_id)
        source_agency = self._source_agency(session.state)
        if session.state is AirportArrivalState.LANDING_CLEARED or (
            session.state is AirportArrivalState.TOWER
            and session.clearance is not None
            and session.clearance.approach_type is ApproachType.VISUAL
        ):
            action = RunwaySightAction.GO_AROUND
            self.runtime.go_around(session_id, reason=reason)
        elif session.clearance is not None and session.clearance.approach_type is ApproachType.VISUAL:
            action = RunwaySightAction.REPOSITION_OR_INSTRUMENT
        else:
            action = RunwaySightAction.CONTINUE
        report = RunwaySightReport(runway_in_sight=False, action=action, reason=reason)
        self._record(session_id, report, source_agency=source_agency)
        return report

    def _require_reportable(self, session_id: UUID):
        session = self.runtime.get(session_id)
        if session is None:
            raise KeyError("Airport arrival session not found")
        if session.state not in self._REPORTABLE_STATES:
            raise ValueError("Runway sight report is not valid from current arrival state")
        return session

    @staticmethod
    def _source_agency(state: AirportArrivalState) -> ControllerAgency:
        if state in {AirportArrivalState.TOWER, AirportArrivalState.LANDING_CLEARED}:
            return ControllerAgency.AIRPORT_TOWER
        return ControllerAgency.AIRPORT_APPROACH

    def _record(
        self,
        session_id: UUID,
        report: RunwaySightReport,
        *,
        source_agency: ControllerAgency,
    ) -> None:
        self.runtime.core.history.record(
            session_id=session_id,
            event_type="airport_arrival_runway_sight_report",
            reason=report.reason,
            source_agency=source_agency,
            details={
                "runway_in_sight": report.runway_in_sight,
                "action": report.action.value,
            },
        )
