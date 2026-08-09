from uuid import uuid4

from orion.airport_surface_runtime import AirportGroundController
from orion.airport_taxi_guidance import TaxiGuidanceAction
from orion.airport_taxi_navigation import (
    AirportSurfaceGraph,
    SurfaceEdge,
    SurfaceNode,
    SurfaceNodeKind,
    SurfacePosition,
)
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


def controller_with_route() -> tuple[AirportGroundController, AirportSurfaceGraph, object]:
    surface = graph()
    controller = AirportGroundController()
    session_id = uuid4()
    controller.assume_surface_control(session_id, reason="ground")
    route = surface.build_taxi_route(session_id=session_id, origin_node_id="stand", destination_node_id="hold", reason="departure")
    controller.issue_taxi_route(route)
    return controller, surface, session_id


def test_deviation_replans_then_immediately_generates_guidance() -> None:
    controller, surface, session_id = controller_with_route()
    cue = controller.guidance_after_position_update(
        session_id=session_id,
        graph=surface,
        position=SurfacePosition(x_m=50, z_m=50),
        freshness=FreshnessClass.FRESH,
    )
    assert cue.action is TaxiGuidanceAction.HOLD_SHORT
    assert cue.text.startswith("Route recalculated.")
    assert "runway 27" in cue.text
    active = controller.surface.get_route(session_id)
    assert active is not None and active.revision == 2


def test_free_form_question_uses_replanned_active_route() -> None:
    controller, surface, session_id = controller_with_route()
    cue = controller.answer_taxi_question(
        session_id=session_id,
        graph=surface,
        position=SurfacePosition(x_m=50, z_m=50),
        freshness=FreshnessClass.FRESH,
        question="куда дальше?",
    )
    assert cue.action is TaxiGuidanceAction.HOLD_SHORT
    assert "runway 27" in cue.text
    active = controller.surface.get_route(session_id)
    assert active is not None and active.origin == "bravo"


def test_uncertain_position_returns_uncertain_guidance_without_replanning() -> None:
    controller, surface, session_id = controller_with_route()
    cue = controller.guidance_after_position_update(
        session_id=session_id,
        graph=surface,
        position=SurfacePosition(x_m=500, z_m=500),
        freshness=FreshnessClass.STALE,
    )
    assert cue.action is TaxiGuidanceAction.POSITION_UNCERTAIN
    active = controller.surface.get_route(session_id)
    assert active is not None and active.revision == 1
