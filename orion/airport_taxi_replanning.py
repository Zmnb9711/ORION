from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from orion.airport_surface import TaxiRoute
from orion.airport_taxi_navigation import AirportSurfaceGraph, PositionMatch, SurfacePosition
from orion.atc_operations import FreshnessClass


class TaxiDeviationState(StrEnum):
    ON_ROUTE = "on_route"
    DEVIATED = "deviated"
    POSITION_UNCERTAIN = "position_uncertain"


class TaxiReplanDecision(BaseModel):
    state: TaxiDeviationState
    matched_node_id: str | None = None
    reason: str = Field(min_length=1, max_length=500)
    replacement_route: TaxiRoute | None = None


class TaxiRouteReplanner:
    """Detects route deviation and safely replans from reliable surface position evidence."""

    def __init__(self, graph: AirportSurfaceGraph) -> None:
        self.graph = graph

    def evaluate(
        self,
        *,
        session_id: UUID,
        active_route: TaxiRoute,
        position: SurfacePosition,
        freshness: FreshnessClass,
        reason: str = "aircraft deviated from active taxi route",
        max_match_distance_m: float = 35.0,
    ) -> TaxiReplanDecision:
        if active_route.facility_id != self.graph.facility_id:
            raise ValueError("Taxi route and surface graph facility mismatch")
        match = self.graph.match_position(
            position,
            freshness=freshness,
            max_match_distance_m=max_match_distance_m,
        )
        if not match.sufficiently_known or match.node_id is None:
            return TaxiReplanDecision(
                state=TaxiDeviationState.POSITION_UNCERTAIN,
                matched_node_id=match.node_id,
                reason=match.reason,
            )

        planned_nodes = self._route_nodes(active_route)
        if match.node_id in planned_nodes:
            return TaxiReplanDecision(
                state=TaxiDeviationState.ON_ROUTE,
                matched_node_id=match.node_id,
                reason="aircraft remains on the active taxi route",
            )

        replacement = self.graph.build_taxi_route(
            session_id=session_id,
            origin_node_id=match.node_id,
            destination_node_id=active_route.destination,
            reason=reason,
            revision=active_route.revision + 1,
        )
        return TaxiReplanDecision(
            state=TaxiDeviationState.DEVIATED,
            matched_node_id=match.node_id,
            reason=reason,
            replacement_route=replacement,
        )

    def _route_nodes(self, route: TaxiRoute) -> set[str]:
        nodes = {route.origin, route.destination}
        for segment in route.segments:
            edge = self.graph.edge(segment.segment_id)
            nodes.add(edge.start_node_id)
            nodes.add(edge.end_node_id)
        return nodes
