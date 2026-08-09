from uuid import uuid4

import pytest

from orion.airport_taxi_navigation import (
    AirportSurfaceGraph,
    SurfaceEdge,
    SurfaceEdgeKind,
    SurfaceNode,
    SurfaceNodeKind,
    SurfacePosition,
)
from orion.atc_operations import FreshnessClass


def _graph() -> AirportSurfaceGraph:
    graph = AirportSurfaceGraph(facility_id="kutaisi", version=3)
    graph.add_node(
        SurfaceNode(
            node_id="stand-14",
            kind=SurfaceNodeKind.PARKING,
            position=SurfacePosition(x_m=0, z_m=0),
            label="Stand 14",
        )
    )
    graph.add_node(
        SurfaceNode(
            node_id="alpha-1",
            kind=SurfaceNodeKind.INTERSECTION,
            position=SurfacePosition(x_m=100, z_m=0),
            label="Alpha",
        )
    )
    graph.add_node(
        SurfaceNode(
            node_id="hp-07",
            kind=SurfaceNodeKind.HOLDING_POINT,
            position=SurfacePosition(x_m=200, z_m=0),
            label="Holding point runway 07",
            runway_id="07/25",
        )
    )
    graph.add_node(
        SurfaceNode(
            node_id="exit-25",
            kind=SurfaceNodeKind.RUNWAY_EXIT,
            position=SurfacePosition(x_m=200, z_m=100),
            label="Runway exit",
            runway_id="07/25",
        )
    )
    graph.add_edge(
        SurfaceEdge(
            edge_id="apron-to-alpha",
            start_node_id="stand-14",
            end_node_id="alpha-1",
            kind=SurfaceEdgeKind.APRON,
            label="Apron",
            length_m=100,
        )
    )
    graph.add_edge(
        SurfaceEdge(
            edge_id="alpha-to-hp",
            start_node_id="alpha-1",
            end_node_id="hp-07",
            kind=SurfaceEdgeKind.TAXIWAY,
            label="Alpha",
            length_m=100,
        )
    )
    graph.add_edge(
        SurfaceEdge(
            edge_id="exit-to-alpha",
            start_node_id="exit-25",
            end_node_id="alpha-1",
            kind=SurfaceEdgeKind.TAXIWAY,
            label="Alpha",
            length_m=140,
        )
    )
    return graph


def test_position_match_returns_known_node_when_fresh_and_close() -> None:
    match = _graph().match_position(
        SurfacePosition(x_m=4, z_m=3),
        freshness=FreshnessClass.FRESH,
    )

    assert match.node_id == "stand-14"
    assert match.sufficiently_known is True
    assert match.distance_m == pytest.approx(5.0)
    assert match.confidence > 0.8


def test_position_match_fails_closed_when_stale() -> None:
    match = _graph().match_position(
        SurfacePosition(x_m=2, z_m=2),
        freshness=FreshnessClass.STALE,
    )

    assert match.node_id == "stand-14"
    assert match.sufficiently_known is False
    assert "insufficient" in match.reason


def test_position_match_does_not_fake_precision_when_far_from_topology() -> None:
    match = _graph().match_position(
        SurfacePosition(x_m=1000, z_m=1000),
        freshness=FreshnessClass.FRESH,
    )

    assert match.node_id is None
    assert match.sufficiently_known is False
    assert match.confidence == 0


def test_departure_route_builds_canonical_taxi_route_and_hold_short() -> None:
    graph = _graph()
    session_id = uuid4()

    route = graph.build_taxi_route(
        session_id=session_id,
        origin_node_id="stand-14",
        destination_node_id="hp-07",
        reason="taxi to runway 07 holding point",
    )

    assert route.session_id == session_id
    assert route.facility_id == "kutaisi"
    assert [segment.segment_id for segment in route.segments] == ["apron-to-alpha", "alpha-to-hp"]
    assert route.hold_short_resources == ["07/25"]
    assert route.runway_crossings == []
    assert route.topology_version == 3


def test_arrival_route_plans_from_runway_exit_back_to_stand() -> None:
    route = _graph().build_taxi_route(
        session_id=uuid4(),
        origin_node_id="exit-25",
        destination_node_id="stand-14",
        reason="taxi to parking after runway vacated",
    )

    assert [segment.segment_id for segment in route.segments] == ["exit-to-alpha", "apron-to-alpha"]
    assert route.destination == "stand-14"


def test_blocked_edge_is_not_used() -> None:
    graph = _graph()
    graph.add_node(
        SurfaceNode(
            node_id="bravo-1",
            kind=SurfaceNodeKind.INTERSECTION,
            position=SurfacePosition(x_m=100, z_m=50),
            label="Bravo",
        )
    )
    graph.add_edge(
        SurfaceEdge(
            edge_id="blocked-shortcut",
            start_node_id="stand-14",
            end_node_id="hp-07",
            length_m=10,
            blocked=True,
        )
    )

    path = graph.shortest_path("stand-14", "hp-07")

    assert path.edge_ids == ["apron-to-alpha", "alpha-to-hp"]
    assert path.total_distance_m == pytest.approx(200)


def test_runway_crossing_is_explicit_in_generated_taxi_route() -> None:
    graph = _graph()
    graph.add_node(
        SurfaceNode(
            node_id="south-side",
            kind=SurfaceNodeKind.INTERSECTION,
            position=SurfacePosition(x_m=300, z_m=0),
        )
    )
    graph.add_edge(
        SurfaceEdge(
            edge_id="cross-07-25",
            start_node_id="hp-07",
            end_node_id="south-side",
            kind=SurfaceEdgeKind.RUNWAY_CROSSING,
            runway_id="07/25",
            length_m=80,
        )
    )

    route = graph.build_taxi_route(
        session_id=uuid4(),
        origin_node_id="stand-14",
        destination_node_id="south-side",
        reason="route requires runway crossing",
    )

    assert route.runway_crossings == ["07/25"]
    assert route.hold_short_resources == ["07/25"]


def test_no_route_fails_closed_instead_of_inventing_guidance() -> None:
    graph = _graph()
    graph.add_node(
        SurfaceNode(
            node_id="isolated",
            kind=SurfaceNodeKind.PARKING,
            position=SurfacePosition(x_m=900, z_m=900),
        )
    )

    with pytest.raises(ValueError, match="No usable taxi route"):
        graph.shortest_path("stand-14", "isolated")
