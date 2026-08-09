from __future__ import annotations

from uuid import UUID

from orion.airport_tower_runtime import (
    AirportTowerController,
    TowerArrivalState,
    TowerDepartureState,
)
from orion.atc_core import ControllerAgency, ControllerAuthorityScope, ControllerHandoffTransaction
from orion.atc_service import VirtualAtcService


AIRBORNE_EVENT = "airborne"
RUNWAY_VACATED_EVENT = "runway_vacated"
DEPARTURE_SERVICE_STATE = "departure_control"
GROUND_SERVICE_STATE = "ground_taxi_in"


class AirportAtcOrchestrator:
    """Coordinates inter-controller airport ATC transitions above procedural engines."""

    def __init__(self, *, service: VirtualAtcService, tower: AirportTowerController) -> None:
        if service.core is not tower.core:
            raise ValueError("Airport ATC orchestration requires one shared ATC core")
        self.service = service
        self.tower = tower
        self.core = service.core
        self._departure_handoffs: dict[UUID, UUID] = {}
        self._completed_departure_handoffs: dict[UUID, UUID] = {}
        self._ground_continuations: set[UUID] = set()
        self._completed_ground_continuations: set[UUID] = set()

    def assume_tower_local_traffic(self, session_id: UUID, *, reason: str) -> None:
        self.service.claim_authority(
            session_id=session_id,
            scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
            agency=ControllerAgency.AIRPORT_TOWER,
            reason=reason,
        )

    def arm_tower_to_departure(
        self,
        session_id: UUID,
        *,
        reason: str,
        frequency: str | None = None,
        channel: str | None = None,
    ) -> ControllerHandoffTransaction:
        if session_id in self._departure_handoffs:
            raise ValueError("Tower to Departure handoff is already armed for this session")
        if session_id in self._completed_departure_handoffs:
            raise ValueError("Tower to Departure handoff is already completed for this session")
        owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
        if owner is None or owner.agency is not ControllerAgency.AIRPORT_TOWER:
            raise ValueError("Tower must own FLIGHT_TRAFFIC before Departure handoff can be armed")
        handoff = self.service.begin_event_gated_handoff(
            session_id=session_id,
            source=ControllerAgency.AIRPORT_TOWER,
            destination=ControllerAgency.AIRPORT_DEPARTURE,
            scopes=[ControllerAuthorityScope.FLIGHT_TRAFFIC],
            reason=reason,
            frequency=frequency,
            channel=channel,
        )
        self._departure_handoffs[session_id] = handoff.handoff_id
        self.core.history.record(
            session_id=session_id,
            event_type="airport_departure_handoff_armed",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            related_id=handoff.handoff_id,
            details={"gate": AIRBORNE_EVENT},
        )
        return handoff

    def complete_tower_to_departure_on_airborne(
        self,
        session_id: UUID,
        *,
        reason: str,
        contact_established: bool | None = None,
    ) -> ControllerHandoffTransaction:
        completed_id = self._completed_departure_handoffs.get(session_id)
        if completed_id is not None:
            completed = self.core.authority.get_handoff(completed_id)
            if completed is None:
                raise RuntimeError("Completed Departure handoff is missing from authority registry")
            return completed
        handoff_id = self._departure_handoffs.get(session_id)
        if handoff_id is None:
            raise ValueError("Tower to Departure handoff is not armed for this session")
        departure = self.tower._require_departure(session_id)
        if departure.state is not TowerDepartureState.AIRBORNE:
            raise ValueError("Tower to Departure handoff requires confirmed AIRBORNE state")
        completed = self.service.complete_event_gated_handoff(
            handoff_id,
            event_name=AIRBORNE_EVENT,
            reason=reason,
            contact_established=contact_established,
        )
        self.service.transition(session_id, DEPARTURE_SERVICE_STATE, reason=reason)
        self._departure_handoffs.pop(session_id, None)
        self._completed_departure_handoffs[session_id] = completed.handoff_id
        self.core.history.record(
            session_id=session_id,
            event_type="airport_departure_authority_transferred",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_DEPARTURE,
            related_id=completed.handoff_id,
            details={"gate": AIRBORNE_EVENT, "procedural_state": DEPARTURE_SERVICE_STATE},
        )
        return completed

    def arm_runway_vacated_to_ground(self, session_id: UUID, *, reason: str) -> None:
        if session_id in self._ground_continuations:
            raise ValueError("Runway-vacated Ground continuation is already armed for this session")
        if session_id in self._completed_ground_continuations:
            raise ValueError("Runway-vacated Ground continuation is already completed for this session")
        tower_owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.LANDING_AREA)
        if tower_owner is None or tower_owner.agency is not ControllerAgency.AIRPORT_TOWER:
            raise ValueError("Tower must own LANDING_AREA before Ground continuation can be armed")
        surface_owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.SURFACE_MOVEMENT)
        if surface_owner is not None:
            raise ValueError("SURFACE_MOVEMENT must be unowned before Ground continuation is armed")
        self._ground_continuations.add(session_id)
        self.core.history.record(
            session_id=session_id,
            event_type="airport_ground_continuation_armed",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            details={"gate": RUNWAY_VACATED_EVENT},
        )

    def complete_ground_continuation_on_runway_vacated(self, session_id: UUID, *, reason: str) -> None:
        if session_id in self._completed_ground_continuations:
            return
        if session_id not in self._ground_continuations:
            raise ValueError("Runway-vacated Ground continuation is not armed for this session")
        arrival = self.tower._require_arrival(session_id)
        if arrival.state is not TowerArrivalState.RUNWAY_VACATED:
            raise ValueError("Ground continuation requires confirmed RUNWAY_VACATED state")
        self.service.claim_authority(
            session_id=session_id,
            scope=ControllerAuthorityScope.SURFACE_MOVEMENT,
            agency=ControllerAgency.AIRPORT_GROUND,
            reason=reason,
        )
        self.service.transition(session_id, GROUND_SERVICE_STATE, reason=reason)
        self._ground_continuations.remove(session_id)
        self._completed_ground_continuations.add(session_id)
        self.core.history.record(
            session_id=session_id,
            event_type="airport_ground_surface_authority_acquired",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_GROUND,
            details={"gate": RUNWAY_VACATED_EVENT, "procedural_state": GROUND_SERVICE_STATE},
        )
