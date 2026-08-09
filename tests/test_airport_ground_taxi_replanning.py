from uuid import uuid4

from orion.airport_surface_runtime import AirportGroundController
from orion.airport_taxi_navigation import (
    AirportSurfaceGraph,
    SurfaceEdge,
    SurfaceNode,
    SurfaceNodeKind,
    SurfacePosition,
)
from orion.airport_taxi_replanning import TaxiDeviationState
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


def test_ground_controller_installs_replanned_route_and_audits_it() -> None:
    surface = graph()
    controller = AirportGroundController()
    session_id = uuid4()
    controller.assume_surface_control(session_id, reason="ground")
    route = surface.build_taxi_route(session_id=session_id, origin_node_id="stand", destination_node_id="hold", reason="departure")
    controller.issue_taxi_route(route)

    decision = controller.evaluate_taxi_position(
        session_id=session_id,
        graph=surface,
        position=SurfacePosition(x_m=50, z_m=50),
        freshness=FreshnessClass.FRESH,
    )

    assert decision.state is TaxiDeviationState.DEVIATED
    active = controller.surface.get_route(session_id)
    assert active is not None
    assert active.origin == "bravo"
    assert active.revision == 2
    events = controller.core.history.list_for_session(session_id)
    assert any(event.event_type == "taxi_route_replanned" for event in events)


def test_ground_controller_does_not_replace_route_when_position_uncertain() -> None:
    surface = graph()
    controller = AirportGroundController()
    session_id = uuid4()
    controller.assume_surface_control(session_id, reason="ground")
    route = surface.build_taxi_route(session_id=session_id, origin_node_id="stand", destination_node_id="hold", reason="departure")
    controller.issue_taxi_route(route)

    decision = controller.evaluate_taxi_position(
        session_id=session_id,
        graph=surface,
        position=SurfacePosition(x_m=500, z_m=500),
        freshness=FreshnessClass.STALE,
    )

    assert decision.state is TaxiDeviationState.POSITION_UNCERTAIN
    active = controller.surface.get_route(session_id)
    assert active is not None
    assert active.origin == "stand"
    assert active.revision == 1
    events = controller.core.history.list_for_session(session_id)
    assert any(event.event_type == "taxi_position_uncertain" for event in events)
