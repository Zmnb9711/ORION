from __future__ import annotations

from uuid import UUID

from orion.airport_tower_runtime import AirportTowerController, TowerDepartureState
from orion.atc_core import ControllerAgency, ControllerAuthorityScope, ControllerHandoffTransaction
from orion.atc_service import VirtualAtcService


AIRBORNE_EVENT = "airborne"


class AirportAtcOrchestrator:
    """Coordinates inter-controller airport ATC transitions above procedural engines."""

    def __init__(self, *, service: VirtualAtcService, tower: AirportTowerController) -> None:
        if service.core is not tower.core:
            raise ValueError("Airport ATC orchestration requires one shared ATC core")
        self.service = service
        self.tower = tower
        self.core = service.core
        self._departure_handoffs: dict[UUID, UUID] = {}

    def assume_tower_local_traffic(self, session_id: UUID, *, reason: str) -> None:
        """Give Tower local airborne traffic authority before departure handoff is armed."""
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
        self._departure_handoffs.pop(session_id, None)
        self.core.history.record(
            session_id=session_id,
            event_type="airport_departure_authority_transferred",
            reason=reason,
            source_agency=ControllerAgency.AIRPORT_DEPARTURE,
            related_id=completed.handoff_id,
            details={"gate": AIRBORNE_EVENT},
        )
        return completed
