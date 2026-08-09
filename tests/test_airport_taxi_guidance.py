from uuid import uuid4

from orion.airport_taxi_guidance import TaxiGuidanceAction, TaxiGuidanceEngine
from orion.airport_taxi_navigation import (
    AirportSurfaceGraph,
    PositionMatch,
    SurfaceEdge,
    SurfaceNode,
    SurfaceNodeKind,
    SurfacePosition,
)
from orion.atc_operations import FreshnessClass


def _graph() -> AirportSurfaceGraph:
    graph = AirportSurfaceGraph(facility_id="kutaisi")
    graph.add_node(SurfaceNode(node_id="stand", kind=SurfaceNodeKind.PARKING, position=SurfacePosition(x_m=0, z_m=0), label="Stand 14"))
    graph.add_node(SurfaceNode(node_id="a", kind=SurfaceNodeKind.INTERSECTION, position=SurfacePosition(x_m=100, z_m=0)))
    graph.add_node(SurfaceNode(node_id="b", kind=SurfaceNodeKind.INTERSECTION, position=SurfacePosition(x_m=100, z_m=100)))
    graph.add_node(SurfaceNode(node_id="hp", kind=SurfaceNodeKind.HOLDING_POINT, position=SurfacePosition(x_m=100, z_m=200), runway_id="07"))
    graph.add_edge(SurfaceEdge(edge_id="e1", start_node_id="stand", end_node_id="a", length_m=100, label="Alpha"))
    graph.add_edge(SurfaceEdge(edge_id="e2", start_node_id="a", end_node_id="b", length_m=100, label="Bravo"))
    graph.add_edge(SurfaceEdge(edge_id="e3", start_node_id="b", end_node_id="hp", length_m=100, label="Bravo"))
    return graph


def _match(node_id: str, confidence: float = 0.9) -> PositionMatch:
    return PositionMatch(
        node_id=node_id,
        distance_m=2,
        confidence=confidence,
        freshness=FreshnessClass.FRESH,
        sufficiently_known=True,
        reason="matched",
    )


def test_guidance_emits_turn_left_on_route_geometry() -> None:
    graph = _graph()
    route = graph.build_taxi_route(session_id=uuid4(), origin_node_id="stand", destination_node_id="hp", reason="departure taxi")
    cue = TaxiGuidanceEngine(graph).next_cue(route, _match("a"))
    assert cue.action is TaxiGuidanceAction.TURN_LEFT
    assert cue.named_surface == "Bravo"


def test_guidance_emits_hold_short_before_runway_boundary() -> None:
    graph = _graph()
    route = graph.build_taxi_route(session_id=uuid4(), origin_node_id="stand", destination_node_id="hp", reason="departure taxi")
    cue = TaxiGuidanceEngine(graph).next_cue(route, _match("b"))
    assert cue.action is TaxiGuidanceAction.HOLD_SHORT
    assert cue.safety_critical is True
    assert cue.runway_id == "07"


def test_guidance_fails_closed_on_uncertain_position() -> None:
    graph = _graph()
    route = graph.build_taxi_route(session_id=uuid4(), origin_node_id="stand", destination_node_id="hp", reason="departure taxi")
    cue = TaxiGuidanceEngine(graph).next_cue(
        route,
        PositionMatch(confidence=0.1, freshness=FreshnessClass.STALE, sufficiently_known=False, reason="stale"),
    )
    assert cue.action is TaxiGuidanceAction.POSITION_UNCERTAIN


def test_guidance_detects_off_route_position() -> None:
    graph = _graph()
    graph.add_node(SurfaceNode(node_id="other", kind=SurfaceNodeKind.APRON, position=SurfacePosition(x_m=-100, z_m=-100)))
    route = graph.build_taxi_route(session_id=uuid4(), origin_node_id="stand", destination_node_id="hp", reason="departure taxi")
    cue = TaxiGuidanceEngine(graph).next_cue(route, _match("other"))
    assert cue.action is TaxiGuidanceAction.OFF_ROUTE


def test_free_form_right_question_is_answered_against_route() -> None:
    graph = _graph()
    route = graph.build_taxi_route(session_id=uuid4(), origin_node_id="stand", destination_node_id="hp", reason="departure taxi")
    cue = TaxiGuidanceEngine(graph).answer_free_form(route, _match("a"), "Здесь направо?")
    assert cue.text.startswith("No.")
    assert cue.action is TaxiGuidanceAction.TURN_LEFT


def test_destination_reports_arrival() -> None:
    graph = _graph()
    route = graph.build_taxi_route(session_id=uuid4(), origin_node_id="stand", destination_node_id="hp", reason="departure taxi")
    cue = TaxiGuidanceEngine(graph).next_cue(route, _match("hp"))
    assert cue.action is TaxiGuidanceAction.ARRIVED
