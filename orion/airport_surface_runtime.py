from __future__ import annotations

from threading import RLock
from uuid import UUID

from orion.airport_surface import (
    CrossingState,
    HoldShortConstraint,
    RunwayAvailability,
    RunwayCrossingTransaction,
    RunwayState,
    TaxiRoute,
)
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import OperationalInstruction, ResourceAssignment, VoicePriority
from orion.atc_runtime import AtcCoreFlow


RUNWAY_PROTECTED_RESOURCE = "runway_protected"


class RunwayOccupancyManager:
    """Conservative runway-state registry for airport procedures."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._states: dict[str, RunwayState] = {}

    def observe(self, state: RunwayState) -> RunwayState:
        with self._lock:
            self._states[state.runway_id] = state.model_copy(deep=True)
            return state.model_copy(deep=True)

    def get(self, runway_id: str) -> RunwayState:
        with self._lock:
            state = self._states.get(runway_id)
            if state is None:
                return RunwayState(runway_id=runway_id, reason="runway state not observed")
            return state.model_copy(deep=True)

    def require_positive_clearance_state(self, runway_id: str) -> RunwayState:
        state = self.get(runway_id)
        if not state.usable_for_positive_clearance:
            raise ValueError("Runway state is not safe enough for positive clearance")
        return state

    def mark_reserved(self, runway_id: str, *, reason: str) -> RunwayState:
        with self._lock:
            current = self.get(runway_id)
            if current.availability is not RunwayAvailability.CLEAR:
                raise ValueError("Only a clear runway can be reserved")
            current.availability = RunwayAvailability.RESERVED
            current.reason = reason
            self._states[runway_id] = current.model_copy(deep=True)
            return current.model_copy(deep=True)


class AirportSurfaceCoordinator:
    """Coordinates taxi routes, hold-short constraints and exclusive runway use."""

    def __init__(self, core: AtcCoreFlow | None = None) -> None:
        self.core = core or AtcCoreFlow()
        self.runways = RunwayOccupancyManager()
        self._routes: dict[UUID, TaxiRoute] = {}
        self._holds: dict[tuple[UUID, str], HoldShortConstraint] = {}
        self._crossings: dict[UUID, RunwayCrossingTransaction] = {}

    def set_route(self, route: TaxiRoute) -> TaxiRoute:
        current = self._routes.get(route.session_id)
        if current is not None and route.revision <= current.revision:
            raise ValueError("Taxi route revision must increase")
        self._routes[route.session_id] = route.model_copy(deep=True)
        self.core.history.record(
            session_id=route.session_id,
            event_type="taxi_route_set",
            reason=route.reason,
            source_agency=ControllerAgency.AIRPORT_GROUND,
            related_id=route.route_id,
            details={"revision": route.revision, "topology_version": route.topology_version},
        )
        return route.model_copy(deep=True)

    def add_hold_short(self, constraint: HoldShortConstraint) -> HoldShortConstraint:
        key = (constraint.session_id, constraint.resource_id)
        self._holds[key] = constraint.model_copy(deep=True)
        self.core.history.record(
            session_id=constraint.session_id,
            event_type="hold_short_set",
            reason=constraint.reason,
            source_agency=ControllerAgency.AIRPORT_GROUND,
            related_id=constraint.constraint_id,
            details={"resource_id": constraint.resource_id},
        )
        return constraint.model_copy(deep=True)

    def get_hold_short(self, session_id: UUID, resource_id: str) -> HoldShortConstraint | None:
        item = self._holds.get((session_id, resource_id))
        return item.model_copy(deep=True) if item else None

    def request_crossing(self, crossing: RunwayCrossingTransaction) -> RunwayCrossingTransaction:
        self._crossings[crossing.crossing_id] = crossing.model_copy(deep=True)
        self.core.history.record(
            session_id=crossing.session_id,
            event_type="runway_crossing_requested",
            reason=crossing.reason,
            source_agency=ControllerAgency.AIRPORT_GROUND,
            related_id=crossing.crossing_id,
            details={"runway_id": crossing.runway_id},
        )
        return crossing.model_copy(deep=True)

    def reserve_protected_runway(self, *, session_id: UUID, runway_id: str, reason: str) -> ResourceAssignment:
        self.runways.require_positive_clearance_state(runway_id)
        return self.core.coordination.assign_resource(
            ResourceAssignment(
                session_id=session_id,
                resource_type=RUNWAY_PROTECTED_RESOURCE,
                resource_id=runway_id,
                reason=reason,
            )
        )

    def release_protected_runway(self, *, session_id: UUID, runway_id: str) -> None:
        self.core.coordination.release_resource(
            resource_type=RUNWAY_PROTECTED_RESOURCE,
            resource_id=runway_id,
            session_id=session_id,
        )

    def clear_crossing(self, crossing_id: UUID) -> RunwayCrossingTransaction:
        crossing = self._require_crossing(crossing_id)
        runway = self.runways.require_positive_clearance_state(crossing.runway_id)
        self.reserve_protected_runway(
            session_id=crossing.session_id,
            runway_id=crossing.runway_id,
            reason=f"Runway crossing {crossing.crossing_id}",
        )
        crossing.clear(runway)
        self._crossings[crossing_id] = crossing
        self.core.history.record(
            session_id=crossing.session_id,
            event_type="runway_crossing_cleared",
            reason=crossing.reason,
            source_agency=ControllerAgency.AIRPORT_TOWER,
            related_id=crossing.crossing_id,
            details={"runway_id": crossing.runway_id},
        )
        return crossing.model_copy(deep=True)

    def acknowledge_crossing(self, crossing_id: UUID) -> RunwayCrossingTransaction:
        crossing = self._require_crossing(crossing_id)
        crossing.acknowledge()
        self._crossings[crossing_id] = crossing
        return crossing.model_copy(deep=True)

    def commit_crossing(self, crossing_id: UUID) -> RunwayCrossingTransaction:
        crossing = self._require_crossing(crossing_id)
        crossing.commit()
        self._crossings[crossing_id] = crossing
        hold = self._holds.get((crossing.session_id, crossing.runway_id))
        if hold is not None and hold.active:
            hold.release()
            self._holds[(crossing.session_id, crossing.runway_id)] = hold
        self.core.history.record(
            session_id=crossing.session_id,
            event_type="runway_crossing_committed",
            reason="aircraft physically committed to crossing",
            source_agency=ControllerAgency.AIRPORT_TOWER,
            related_id=crossing.crossing_id,
            details={"runway_id": crossing.runway_id},
        )
        return crossing.model_copy(deep=True)

    def complete_crossing(self, crossing_id: UUID) -> RunwayCrossingTransaction:
        crossing = self._require_crossing(crossing_id)
        crossing.complete()
        self._crossings[crossing_id] = crossing
        self.release_protected_runway(session_id=crossing.session_id, runway_id=crossing.runway_id)
        self.core.history.record(
            session_id=crossing.session_id,
            event_type="runway_crossing_completed",
            reason="aircraft vacated runway crossing resource",
            source_agency=ControllerAgency.AIRPORT_TOWER,
            related_id=crossing.crossing_id,
            details={"runway_id": crossing.runway_id},
        )
        return crossing.model_copy(deep=True)

    def _require_crossing(self, crossing_id: UUID) -> RunwayCrossingTransaction:
        item = self._crossings.get(crossing_id)
        if item is None:
            raise KeyError("Runway crossing transaction not found")
        return item.model_copy(deep=True)


class AirportGroundController:
    """First procedural Ground controller built on Virtual ATC Core."""

    def __init__(self, surface: AirportSurfaceCoordinator | None = None) -> None:
        self.surface = surface or AirportSurfaceCoordinator()
        self.core = self.surface.core

    def assume_surface_control(self, session_id: UUID, *, reason: str) -> None:
        self.core.claim_authority(
            session_id=session_id,
            scope=ControllerAuthorityScope.SURFACE_MOVEMENT,
            agency=ControllerAgency.AIRPORT_GROUND,
            reason=reason,
        )

    def issue_taxi_route(self, route: TaxiRoute) -> OperationalInstruction:
        self.surface.set_route(route)
        instruction = OperationalInstruction(
            session_id=route.session_id,
            issuing_agency=ControllerAgency.AIRPORT_GROUND,
            authority_scope=ControllerAuthorityScope.SURFACE_MOVEMENT,
            semantic_action="taxi_route",
            parameters={
                "destination": route.destination,
                "revision": route.revision,
                "runway_crossings": ",".join(route.runway_crossings),
            },
            acknowledgement_required=True,
            voice_priority=VoicePriority.PROCEDURAL,
        )
        return self.core.issue_instruction(instruction)

    def issue_hold_short(self, constraint: HoldShortConstraint) -> OperationalInstruction:
        self.surface.add_hold_short(constraint)
        instruction = OperationalInstruction(
            session_id=constraint.session_id,
            issuing_agency=ControllerAgency.AIRPORT_GROUND,
            authority_scope=ControllerAuthorityScope.SURFACE_MOVEMENT,
            semantic_action="hold_short",
            parameters={"resource_id": constraint.resource_id},
            acknowledgement_required=True,
            voice_priority=VoicePriority.IMMEDIATE_SAFETY,
        )
        return self.core.issue_instruction(instruction)

    def request_runway_crossing(self, crossing: RunwayCrossingTransaction) -> RunwayCrossingTransaction:
        crossing.hold_short()
        return self.surface.request_crossing(crossing)

    def crossing_state(self, crossing_id: UUID) -> CrossingState:
        return self.surface._require_crossing(crossing_id).state
