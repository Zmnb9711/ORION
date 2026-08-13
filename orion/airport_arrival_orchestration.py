from __future__ import annotations

from uuid import UUID

from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalSession
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_service import VirtualAtcService


ARRIVAL_SERVICE_STATE = "arrival_control"
TOWER_ARRIVAL_SERVICE_STATE = "tower_arrival"
GO_AROUND_SERVICE_STATE = "approach_go_around"
MISSED_APPROACH_SERVICE_STATE = "approach_missed"
REPOSITION_SERVICE_STATE = "approach_reposition"
GROUND_SERVICE_STATE = "ground_taxi_in"


class AirportArrivalOrchestrator:
    """Connects the arrival procedural engine to the persistent ATC service session.

    The procedural engine remains responsible for legal arrival-state transitions and
    controller transactions. This adapter keeps the application-level procedural
    state synchronized so one ATC session survives Approach -> Tower -> Ground and
    the Tower -> Approach go-around loop.
    """

    def __init__(self, *, service: VirtualAtcService, arrival: AirportArrivalRuntime) -> None:
        if service.core is not arrival.core:
            raise ValueError("Airport Arrival orchestration requires one shared ATC core")
        self.service = service
        self.arrival = arrival
        self.core = service.core

    def start_arrival(
        self,
        *,
        session_id: UUID,
        runway_id: str,
        reason: str = "arrival contact established",
    ) -> AirportArrivalSession:
        session = self.arrival.start(session_id=session_id, runway_id=runway_id, reason=reason)
        self.service.transition(session_id, ARRIVAL_SERVICE_STATE, reason=reason)
        self._record_boundary(
            session_id=session_id,
            event_type="airport_arrival_service_started",
            agency=ControllerAgency.AIRPORT_APPROACH,
            reason=reason,
            state=ARRIVAL_SERVICE_STATE,
        )
        return session

    def complete_approach_to_tower(
        self,
        session_id: UUID,
        *,
        reason: str,
    ) -> AirportArrivalSession:
        session = self.arrival.complete_tower_handoff(session_id, reason=reason)
        owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
        if owner is None or owner.agency is not ControllerAgency.AIRPORT_TOWER:
            raise RuntimeError("Approach to Tower handoff completed without Tower FLIGHT_TRAFFIC authority")
        self.service.transition(session_id, TOWER_ARRIVAL_SERVICE_STATE, reason=reason)
        self._record_boundary(
            session_id=session_id,
            event_type="airport_arrival_tower_service_active",
            agency=ControllerAgency.AIRPORT_TOWER,
            reason=reason,
            state=TOWER_ARRIVAL_SERVICE_STATE,
        )
        return session

    def complete_runway_vacated_to_ground(
        self,
        session_id: UUID,
        *,
        reason: str,
    ) -> AirportArrivalSession:
        session = self.arrival.transfer_to_ground(session_id, reason=reason)
        owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.SURFACE_MOVEMENT)
        if owner is None or owner.agency is not ControllerAgency.AIRPORT_GROUND:
            raise RuntimeError("Ground transfer completed without Ground SURFACE_MOVEMENT authority")
        self.service.transition(session_id, GROUND_SERVICE_STATE, reason=reason)
        self._record_boundary(
            session_id=session_id,
            event_type="airport_arrival_ground_service_active",
            agency=ControllerAgency.AIRPORT_GROUND,
            reason=reason,
            state=GROUND_SERVICE_STATE,
        )
        return session

    def go_around_to_approach(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        session = self.arrival.go_around(session_id, reason=reason)
        owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
        if owner is None or owner.agency is not ControllerAgency.AIRPORT_APPROACH:
            raise RuntimeError("Go-around did not restore Approach FLIGHT_TRAFFIC authority")
        self.service.transition(session_id, GO_AROUND_SERVICE_STATE, reason=reason)
        self._record_boundary(
            session_id=session_id,
            event_type="airport_arrival_go_around_service_active",
            agency=ControllerAgency.AIRPORT_APPROACH,
            reason=reason,
            state=GO_AROUND_SERVICE_STATE,
        )
        return session

    def enter_missed_approach(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        session = self.arrival.enter_missed_approach(session_id, reason=reason)
        self.service.transition(session_id, MISSED_APPROACH_SERVICE_STATE, reason=reason)
        return session

    def reposition(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        session = self.arrival.reposition(session_id, reason=reason)
        self.service.transition(session_id, REPOSITION_SERVICE_STATE, reason=reason)
        return session

    def _record_boundary(
        self,
        *,
        session_id: UUID,
        event_type: str,
        agency: ControllerAgency,
        reason: str,
        state: str,
    ) -> None:
        self.core.history.record(
            session_id=session_id,
            event_type=event_type,
            reason=reason,
            source_agency=agency,
            details={"procedural_state": state},
        )
