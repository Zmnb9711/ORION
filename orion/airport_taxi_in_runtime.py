from __future__ import annotations

from uuid import UUID

from orion.airport_surface_runtime import AirportGroundController
from orion.airport_taxi_guidance import TaxiGuidanceAction, TaxiGuidanceCue
from orion.airport_taxi_in import ParkingSelection, ParkingStandCatalog
from orion.airport_taxi_navigation import AirportSurfaceGraph, SurfacePosition
from orion.airport_tower_runtime import AirportTowerController, TowerArrivalState
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import FreshnessClass, OperationalInstruction


class AirportTaxiInRuntime:
    """Runs taxi-in from confirmed runway vacation through arrival at the selected stand."""

    def __init__(
        self,
        *,
        ground: AirportGroundController,
        tower: AirportTowerController,
        graph: AirportSurfaceGraph,
        stands: ParkingStandCatalog,
    ) -> None:
        if ground.core is not tower.core:
            raise ValueError("Taxi-in runtime requires Ground and Tower to share one ATC core")
        if stands.graph is not graph:
            raise ValueError("Parking catalog must use the same surface graph")
        self.ground = ground
        self.tower = tower
        self.graph = graph
        self.stands = stands

    def start_taxi_in(
        self,
        *,
        session_id: UUID,
        runway_exit_node_id: str,
        requested_stand_id: str | None = None,
    ) -> tuple[ParkingSelection, OperationalInstruction]:
        arrival = self.tower._require_arrival(session_id)
        if arrival.state is not TowerArrivalState.RUNWAY_VACATED:
            raise ValueError("Taxi-in cannot start before confirmed RUNWAY_VACATED")
        owner = self.ground.core.authority.get_owner(session_id, ControllerAuthorityScope.SURFACE_MOVEMENT)
        if owner is None or owner.agency is not ControllerAgency.AIRPORT_GROUND:
            raise ValueError("Ground must own SURFACE_MOVEMENT before taxi-in can start")

        exit_node = self.graph.node(runway_exit_node_id)
        if exit_node.kind.value != "runway_exit":
            raise ValueError("Taxi-in origin must be a RUNWAY_EXIT surface node")

        selection = self.stands.select(requested_stand_id)
        current = self.ground.surface.get_route(session_id)
        revision = current.revision + 1 if current is not None else 1
        route = self.graph.build_taxi_route(
            session_id=session_id,
            origin_node_id=runway_exit_node_id,
            destination_node_id=selection.stand.node_id,
            reason=selection.reason,
            revision=revision,
        )
        instruction = self.ground.issue_taxi_route(route)
        self.ground.core.history.record(
            session_id=session_id,
            event_type="taxi_in_started",
            reason=selection.reason,
            source_agency=ControllerAgency.AIRPORT_GROUND,
            related_id=route.route_id,
            details={
                "runway_exit_node_id": runway_exit_node_id,
                "stand_id": selection.stand.stand_id,
                "requested": selection.requested,
                "route_revision": route.revision,
            },
        )
        return selection, instruction

    def update_position(
        self,
        *,
        session_id: UUID,
        position: SurfacePosition,
        freshness: FreshnessClass,
    ) -> TaxiGuidanceCue:
        cue = self.ground.guidance_after_position_update(
            session_id=session_id,
            graph=self.graph,
            position=position,
            freshness=freshness,
        )
        if cue.action is TaxiGuidanceAction.ARRIVED:
            route = self.ground.surface.get_route(session_id)
            if route is None:
                raise ValueError("No active taxi-in route at stand arrival")
            stand = self.stands.get_by_node(route.destination)
            self.ground.core.history.record(
                session_id=session_id,
                event_type="taxi_in_completed",
                reason="aircraft reached assigned parking stand",
                source_agency=ControllerAgency.AIRPORT_GROUND,
                related_id=route.route_id,
                details={
                    "destination_node_id": route.destination,
                    "stand_id": stand.stand_id if stand is not None else route.destination,
                    "route_revision": route.revision,
                },
            )
        return cue
