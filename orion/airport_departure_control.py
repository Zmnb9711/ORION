from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from orion.aerodrome_information import AerodromePressureObservation
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import OperationalInstruction, VoicePriority


class DepartureRoute(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    fixes: list[str] = Field(default_factory=list)
    transition_fix: str | None = Field(default=None, max_length=80)


class DeparturePressureContext(BaseModel):
    transition_altitude_ft: int | None = Field(default=None, ge=0)
    transition_level: int | None = Field(default=None, ge=0)


class DepartureClearance(BaseModel):
    heading_deg: int | None = Field(default=None, ge=0, le=359)
    altitude_ft: int | None = Field(default=None, ge=0)
    direct_to: str | None = Field(default=None, max_length=80)
    route: DepartureRoute | None = None
    speed_kt: int | None = Field(default=None, ge=0)
    frequency_mhz: float | None = Field(default=None, gt=0)
    qnh_hpa: float | None = Field(default=None, gt=0)
    standard_pressure: bool | None = None

    def parameters(self) -> dict[str, str | int | float | bool]:
        values: dict[str, str | int | float | bool] = {}
        if self.heading_deg is not None:
            values["heading_deg"] = self.heading_deg
        if self.altitude_ft is not None:
            values["altitude_ft"] = self.altitude_ft
        if self.direct_to is not None:
            values["direct_to"] = self.direct_to
        if self.route is not None:
            if self.route.name is not None:
                values["route_name"] = self.route.name
            if self.route.fixes:
                values["route_fixes"] = ",".join(self.route.fixes)
            if self.route.transition_fix is not None:
                values["transition_fix"] = self.route.transition_fix
        if self.speed_kt is not None:
            values["speed_kt"] = self.speed_kt
        if self.frequency_mhz is not None:
            values["frequency_mhz"] = self.frequency_mhz
        if self.qnh_hpa is not None:
            values["qnh_hpa"] = self.qnh_hpa
        if self.standard_pressure is not None:
            values["standard_pressure"] = self.standard_pressure
        return values


class AirportDepartureController:
    """Initial airborne Departure controller clearance layer."""

    def __init__(self, core) -> None:
        self.core = core
        self._clearances: dict[UUID, DepartureClearance] = {}

    def issue_clearance(self, session_id: UUID, clearance: DepartureClearance, *, reason: str) -> OperationalInstruction:
        self._require_departure_authority(session_id)
        if not clearance.parameters():
            raise ValueError("Departure clearance must contain at least one known instruction")
        instruction = self.core.issue_instruction(
            OperationalInstruction(
                session_id=session_id,
                issuing_agency=ControllerAgency.AIRPORT_DEPARTURE,
                authority_scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
                semantic_action="departure_clearance",
                parameters=clearance.parameters(),
                acknowledgement_required=True,
                voice_priority=VoicePriority.PROCEDURAL,
            )
        )
        self._clearances[session_id] = clearance.model_copy(deep=True)
        self.core.history.record(
            session_id=session_id,
            event_type="departure_clearance_issued",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_DEPARTURE,
            details=clearance.parameters(),
        )
        return instruction

    def amend_clearance(self, session_id: UUID, amendment: DepartureClearance, *, reason: str) -> OperationalInstruction:
        self._require_departure_authority(session_id)
        if not amendment.model_fields_set:
            raise ValueError("Departure amendment must contain at least one known instruction")
        current = self._clearances.get(session_id, DepartureClearance())
        update = {name: getattr(amendment, name) for name in amendment.model_fields_set}
        merged = current.model_copy(update=update, deep=True)
        return self.issue_clearance(session_id, merged, reason=reason)

    def pressure_clearance(
        self,
        *,
        altitude_ft: int,
        pressure: AerodromePressureObservation | None,
        context: DeparturePressureContext,
    ) -> DepartureClearance:
        if context.transition_altitude_ft is not None and altitude_ft >= context.transition_altitude_ft:
            return DepartureClearance(standard_pressure=True)
        if pressure is not None and pressure.usable_for_current_pressure_answer:
            return DepartureClearance(qnh_hpa=pressure.qnh_hpa, standard_pressure=False)
        return DepartureClearance()

    def current_clearance(self, session_id: UUID) -> DepartureClearance | None:
        item = self._clearances.get(session_id)
        return item.model_copy(deep=True) if item else None

    def answer(self, session_id: UUID, question: str) -> str:
        clearance = self._clearances.get(session_id)
        if clearance is None:
            return "No active Departure clearance is recorded."
        q = question.casefold()
        if "heading" in q or "курс" in q:
            return f"Assigned heading {clearance.heading_deg:03d}." if clearance.heading_deg is not None else "No assigned heading is recorded."
        if "altitude" in q or "высот" in q:
            return f"Cleared altitude {clearance.altitude_ft} feet." if clearance.altitude_ft is not None else "No cleared altitude is recorded."
        if "frequency" in q or "частот" in q:
            return f"Departure frequency {clearance.frequency_mhz:.3f} MHz." if clearance.frequency_mhz is not None else "Departure frequency is not available."
        if "pressure" in q or "давлен" in q or "qnh" in q:
            if clearance.standard_pressure is True:
                return "Set STANDARD 1013.25 hPa / 29.92 inHg."
            if clearance.qnh_hpa is not None:
                return f"Set QNH {clearance.qnh_hpa:.0f} hPa."
            return "No reliable pressure setting is recorded."
        if "direct" in q or "точк" in q or "маршрут" in q or "route" in q:
            if clearance.direct_to is not None:
                return f"Proceed direct {clearance.direct_to}."
            if clearance.route is not None and clearance.route.name is not None:
                return f"Continue via {clearance.route.name}."
            return "No reliable departure route is recorded."
        return "Current Departure clearance is available; ask for heading, altitude, route, frequency, or pressure."

    def _require_departure_authority(self, session_id: UUID) -> None:
        owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
        if owner is None or owner.agency is not ControllerAgency.AIRPORT_DEPARTURE:
            raise ValueError("Departure must own FLIGHT_TRAFFIC before issuing airborne clearances")
