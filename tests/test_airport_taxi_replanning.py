from uuid import uuid4

import pytest

from orion.airport_taxi_navigation import (
    AirportSurfaceGraph,
    SurfaceEdge,
    SurfaceNode,
    SurfaceNodeKind,
    SurfacePosition,
)
from orion.airport_taxi_replanning import TaxiDeviationState, TaxiRouteReplanner
from orion.atc_operations import FreshnessClass


def graph() -> AirportSurfaceGraph:
    item = AirportSurfaceGraph(facility_id="TEST")
    item.add_node(SurfaceNode(node_id="stand", kind=SurfaceNodeKind.PARKING, position=SurfacePosition(x_m=0, z_m=0)))
    item.add_node(SurfaceNode(node_id="alpha", kind=SurfaceNodeKind.INTERSECTION, position=SurfacePosition(x_m=50, z_m=0)))
    item.add_node(SurfaceNode(node_id="hold", kind=SurfaceNodeKind.HOLDING_POINT, position=SurfacePosition(x_m=100, z_m=0), runway_id="27"))
    item.add_node(SurfaceNode(node_id="bravo", kind=SurfaceNodeKind.INTERSECTION, position=SurfacePosition(x_m=50, z_m=50)))
    item.add_edge(SurfaceEdge(edge_id="stand-alpha", start_node_id="stand", end_node_id="alpha", length_m=50))
    item.add_edge(SurfaceEdge(edge_id="alpha-hold", start_node_id="alpha", end_node_id="hold", length_m=50))
    item.add_edge(SurfaceEdge(edge_id="bravo-hold", start_node_id="bravo", end_node_id="hold", length_m=70))
    return item


def test_on_route_position_does_not_replan() -> None:
    surface = graph()
    session_id = uuid4()
    route = surface.build_taxi_route(session_id=session_id, origin_node_id="stand", destination_node_id="hold", reason="departure")
    decision = TaxiRouteReplanner(surface).evaluate(
        session_id=session_id,
        active_route=route,
        position=SurfacePosition(x_m=50, z_m=0),
        freshness=FreshnessClass.FRESH,
    )
    assert decision.state is TaxiDeviationState.ON_ROUTE
    assert decision.replacement_route is None


def test_off_route_position_creates_incremented_replacement_route() -> None:
    surface = graph()
    session_id = uuid4()
    route = surface.build_taxi_route(session_id=session_id, origin_node_id="stand", destination_node_id="hold", reason="departure", revision=3)
    decision = TaxiRouteReplanner(surface).evaluate(
        session_id=session_id,
        active_route=route,
        position=SurfacePosition(x_m=50, z_m=50),
        freshness=FreshnessClass.FRESH,
    )
    assert decision.state is TaxiDeviationState.DEVIATED
    assert decision.matched_node_id == "bravo"
    assert decision.replacement_route is not None
    assert decision.replacement_route.origin == "bravo"
    assert decision.replacement_route.destination == "hold"
    assert decision.replacement_route.revision == 4


def test_uncertain_position_never_fabricates_replan() -> None:
    surface = graph()
    session_id = uuid4()
    route = surface.build_taxi_route(session_id=session_id, origin_node_id="stand", destination_node_id="hold", reason="departure")
    decision = TaxiRouteReplanner(surface).evaluate(
        session_id=session_id,
        active_route=route,
        position=SurfacePosition(x_m=500, z_m=500),
        freshness=FreshnessClass.STALE,
    )
    assert decision.state is TaxiDeviationState.POSITION_UNCERTAIN
    assert decision.replacement_route is None


def test_replanner_rejects_facility_mismatch() -> None:
    surface = graph()
    other = AirportSurfaceGraph(facility_id="OTHER")
    session_id = uuid4()
    route = surface.build_taxi_route(session_id=session_id, origin_node_id="stand", destination_node_id="hold", reason="departure")
    with pytest.raises(ValueError, match="facility mismatch"):
        TaxiRouteReplanner(other).evaluate(
            session_id=session_id,
            active_route=route,
            position=SurfacePosition(x_m=0, z_m=0),
            freshness=FreshnessClass.FRESH,
        )
