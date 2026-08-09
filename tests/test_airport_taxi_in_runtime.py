from uuid import uuid4

import pytest

from orion.airport_surface import RunwayAvailability, RunwayState
from orion.airport_surface_runtime import AirportGroundController, AirportSurfaceCoordinator
from orion.airport_taxi_in import ParkingStand, ParkingStandCatalog
from orion.airport_taxi_in_runtime import AirportTaxiInRuntime
from orion.airport_taxi_navigation import (
    AirportSurfaceGraph,
    SurfaceEdge,
    SurfaceNode,
    SurfaceNodeKind,
    SurfacePosition,
)
from orion.airport_tower_runtime import AirportTowerController


def make_graph() -> AirportSurfaceGraph:
    graph = AirportSurfaceGraph(facility_id="TEST")
    graph.add_node(SurfaceNode(node_id="exit", kind=SurfaceNodeKind.RUNWAY_EXIT, position=SurfacePosition(x_m=0, z_m=0)))
    graph.add_node(SurfaceNode(node_id="apron", kind=SurfaceNodeKind.APRON, position=SurfacePosition(x_m=50, z_m=0)))
    graph.add_node(SurfaceNode(node_id="stand-1", kind=SurfaceNodeKind.PARKING, position=SurfacePosition(x_m=100, z_m=-20), label="Stand 1"))
    graph.add_node(SurfaceNode(node_id="stand-2", kind=SurfaceNodeKind.PARKING, position=SurfacePosition(x_m=100, z_m=20), label="Stand 2"))
    graph.add_edge(SurfaceEdge(edge_id="exit-apron", start_node_id="exit", end_node_id="apron", length_m=50, label="Alpha"))
    graph.add_edge(SurfaceEdge(edge_id="apron-s1", start_node_id="apron", end_node_id="stand-1", length_m=55))
    graph.add_edge(SurfaceEdge(edge_id="apron-s2", start_node_id="apron", end_node_id="stand-2", length_m=55))
    return graph


def make_runtime() -> tuple[AirportTaxiInRuntime, AirportGroundController, AirportTowerController, object]:
    surface = AirportSurfaceCoordinator()
    ground = AirportGroundController(surface)
    tower = AirportTowerController(surface)
    graph = make_graph()
    stands = ParkingStandCatalog(graph)
    stands.add(ParkingStand(stand_id="1", node_id="stand-1", priority=20))
    stands.add(ParkingStand(stand_id="2", node_id="stand-2", priority=10))
    runtime = AirportTaxiInRuntime(ground=ground, tower=tower, graph=graph, stands=stands)
    return runtime, ground, tower, surface


def prepare_vacated_arrival(ground: AirportGroundController, tower: AirportTowerController, surface: AirportSurfaceCoordinator, session_id) -> None:
    tower.assume_runway_control(session_id, reason="arrival")
    surface.runways.observe(RunwayState(runway_id="27", availability=RunwayAvailability.CLEAR, confidence=1.0, reason="observed clear"))
    tower.start_arrival(session_id=session_id, runway_id="27")
    tower.clear_landing(session_id, reason="landing")
    tower.begin_landing_attempt(session_id)
    tower.mark_rollout(session_id)
    tower.mark_runway_vacated(session_id)
    ground.assume_surface_control(session_id, reason="runway vacated")


def test_taxi_in_accepts_pilot_requested_stand() -> None:
    runtime, ground, tower, surface = make_runtime()
    session_id = uuid4()
    prepare_vacated_arrival(ground, tower, surface, session_id)
    selection, instruction = runtime.start_taxi_in(session_id=session_id, runway_exit_node_id="exit", requested_stand_id="1")
    assert selection.requested is True
    assert selection.stand.stand_id == "1"
    assert instruction.parameters["destination"] == "stand-1"
    route = ground.surface.get_route(session_id)
    assert route is not None and route.origin == "exit" and route.destination == "stand-1"


def test_taxi_in_selects_best_available_stand_deterministically() -> None:
    runtime, ground, tower, surface = make_runtime()
    session_id = uuid4()
    prepare_vacated_arrival(ground, tower, surface, session_id)
    selection, _ = runtime.start_taxi_in(session_id=session_id, runway_exit_node_id="exit")
    assert selection.stand.stand_id == "2"


def test_taxi_in_is_blocked_before_runway_vacated() -> None:
    runtime, ground, tower, surface = make_runtime()
    session_id = uuid4()
    tower.start_arrival(session_id=session_id, runway_id="27")
    ground.assume_surface_control(session_id, reason="test")
    with pytest.raises(ValueError, match="RUNWAY_VACATED"):
        runtime.start_taxi_in(session_id=session_id, runway_exit_node_id="exit")


def test_taxi_in_requires_ground_surface_authority() -> None:
    runtime, ground, tower, surface = make_runtime()
    session_id = uuid4()
    tower.assume_runway_control(session_id, reason="arrival")
    surface.runways.observe(RunwayState(runway_id="27", availability=RunwayAvailability.CLEAR, confidence=1.0, reason="observed clear"))
    tower.start_arrival(session_id=session_id, runway_id="27")
    tower.clear_landing(session_id, reason="landing")
    tower.begin_landing_attempt(session_id)
    tower.mark_rollout(session_id)
    tower.mark_runway_vacated(session_id)
    with pytest.raises(ValueError, match="SURFACE_MOVEMENT"):
        runtime.start_taxi_in(session_id=session_id, runway_exit_node_id="exit")
