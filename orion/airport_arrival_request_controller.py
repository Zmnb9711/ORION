from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from orion.aerodrome_information import AerodromePressureObservation
from orion.airport_arrival_information import AirportArrivalInformationController
from orion.airport_arrival_reports import AirportArrivalReportController
from orion.airport_arrival_requests import ArrivalRequestIntent, classify_arrival_request
from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalState, ApproachType


class ArrivalRequestAction(StrEnum):
    ARRIVAL_CONTROL = "arrival_control"
    APPROACH_CHANGED = "approach_changed"
    VECTOR_ISSUED = "vector_issued"
    INFORMATION = "information"
    RUNWAY_REPORT = "runway_report"
    GO_AROUND = "go_around"
    NEEDS_PARAMETER = "needs_parameter"
    UNKNOWN = "unknown"


class ArrivalRequestResult(BaseModel):
    intent: ArrivalRequestIntent
    action: ArrivalRequestAction
    details: dict[str, str | int | float] = Field(default_factory=dict)


class AirportArrivalRequestController:
    """Executes classified free-form arrival requests against the active runtime."""

    def __init__(self, runtime: AirportArrivalRuntime) -> None:
        self.runtime = runtime
        self.information = AirportArrivalInformationController(runtime)
        self.reports = AirportArrivalReportController(runtime)

    def handle(
        self,
        *,
        session_id: UUID,
        text: str,
        altitude_ft: int | None = None,
        heading_deg: int | None = None,
        pressure: AerodromePressureObservation | None = None,
    ) -> ArrivalRequestResult:
        request = classify_arrival_request(text)
        intent = request.intent
        session = self.runtime.get(session_id)
        if session is None:
            raise KeyError("Airport arrival session not found")

        if intent is ArrivalRequestIntent.RETURN_TO_BASE:
            if session.state is AirportArrivalState.ARRIVAL_CONTACT:
                self.runtime.assume_arrival_control(session_id, reason=request.raw_text)
            elif session.state is not AirportArrivalState.ARRIVAL_CONTROL:
                raise ValueError("Return-to-base request is only valid when establishing arrival control")
            return ArrivalRequestResult(intent=intent, action=ArrivalRequestAction.ARRIVAL_CONTROL)

        approach_by_intent = {
            ArrivalRequestIntent.REQUEST_ILS: ApproachType.ILS,
            ArrivalRequestIntent.REQUEST_TACAN: ApproachType.TACAN,
            ArrivalRequestIntent.REQUEST_VISUAL: ApproachType.VISUAL,
        }
        approach_type = approach_by_intent.get(intent)
        if approach_type is not None:
            if session.state is AirportArrivalState.APPROACH_POSITIONING:
                self.runtime.clear_approach(session_id, approach_type=approach_type, reason=request.raw_text)
            elif session.state is AirportArrivalState.APPROACH:
                self.runtime.amend_approach_clearance(session_id, approach_type=approach_type, reason=request.raw_text)
            else:
                raise ValueError("Approach type request is not valid from current arrival state")
            return ArrivalRequestResult(
                intent=intent,
                action=ArrivalRequestAction.APPROACH_CHANGED,
                details={"approach_type": approach_type.value},
            )

        if intent in {ArrivalRequestIntent.REQUEST_LOWER, ArrivalRequestIntent.REQUEST_VECTOR}:
            if intent is ArrivalRequestIntent.REQUEST_LOWER and altitude_ft is None:
                return ArrivalRequestResult(intent=intent, action=ArrivalRequestAction.NEEDS_PARAMETER)
            if intent is ArrivalRequestIntent.REQUEST_VECTOR and heading_deg is None:
                return ArrivalRequestResult(intent=intent, action=ArrivalRequestAction.NEEDS_PARAMETER)
            self.runtime.issue_descent_vectors(
                session_id,
                altitude_ft=altitude_ft if intent is ArrivalRequestIntent.REQUEST_LOWER else None,
                heading_deg=heading_deg if intent is ArrivalRequestIntent.REQUEST_VECTOR else None,
                reason=request.raw_text,
            )
            details: dict[str, str | int | float] = {}
            if altitude_ft is not None:
                details["altitude_ft"] = altitude_ft
            if heading_deg is not None:
                details["heading_deg"] = heading_deg
            return ArrivalRequestResult(intent=intent, action=ArrivalRequestAction.VECTOR_ISSUED, details=details)

        if intent in {ArrivalRequestIntent.REQUEST_QNH, ArrivalRequestIntent.REQUEST_ACTIVE_RUNWAY}:
            answer = self.information.answer(session_id=session_id, intent=intent, pressure=pressure)
            return ArrivalRequestResult(intent=intent, action=ArrivalRequestAction.INFORMATION, details=answer.data)

        if intent is ArrivalRequestIntent.REPORT_RUNWAY_IN_SIGHT:
            report = self.reports.report_runway_in_sight(session_id, reason=request.raw_text)
            return ArrivalRequestResult(
                intent=intent,
                action=ArrivalRequestAction.RUNWAY_REPORT,
                details={"report_action": report.action.value},
            )

        if intent is ArrivalRequestIntent.REPORT_RUNWAY_NOT_IN_SIGHT:
            report = self.reports.report_runway_not_in_sight(session_id, reason=request.raw_text)
            return ArrivalRequestResult(
                intent=intent,
                action=ArrivalRequestAction.RUNWAY_REPORT,
                details={"report_action": report.action.value},
            )

        if intent is ArrivalRequestIntent.GO_AROUND:
            self.runtime.go_around(session_id, reason=request.raw_text)
            return ArrivalRequestResult(intent=intent, action=ArrivalRequestAction.GO_AROUND)

        return ArrivalRequestResult(intent=intent, action=ArrivalRequestAction.UNKNOWN)
