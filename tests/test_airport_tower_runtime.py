from uuid import uuid4

import pytest

from orion.airport_surface import RunwayAvailability, RunwayCrossingTransaction, RunwayState
from orion.airport_surface_runtime import AirportGroundController, AirportSurfaceCoordinator
from orion.airport_tower_runtime import (
    AirportTowerController,
    RunwayOperationKind,
    TowerArrivalState,
    TowerDepartureState,
)
from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import FreshnessClass
from orion.atc_runtime import AtcCoreFlow


def _surface() -> tuple[AtcCoreFlow, AirportSurfaceCoordinator]:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    surface.runways.observe(
        RunwayState(
            runway_id="07/25",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="fresh runway observation",
        )
    )
    return core, surface


def test_ground_tower_boundary_preserves_separate_authority_scopes() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="viper", facility_id="kutaisi")
    core.open_session(identity)
    ground = AirportGroundController(surface)
    tower = AirportTowerController(surface)
    ground.assume_surface_control(identity.session_id, reason="Ground owns taxi movement")
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")

    tower.record_ground_boundary_contact(identity.session_id, reason="aircraft reached holding point")

    assert core.authority.get_owner(identity.session_id, ControllerAuthorityScope.SURFACE_MOVEMENT).agency is ControllerAgency.AIRPORT_GROUND
    assert core.authority.get_owner(identity.session_id, ControllerAuthorityScope.LANDING_AREA).agency is ControllerAgency.AIRPORT_TOWER
    assert any(event.event_type == "ground_tower_boundary_contact" for event in core.history.list(identity.session_id))


def test_takeoff_reservation_blocks_crossing_on_same_runway() -> None:
    core, surface = _surface()
    departure = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    taxi = AtcSessionIdentity(mission_id="m1", aircraft_id="a2", facility_id="kutaisi")
    core.open_session(departure)
    core.open_session(taxi)
    tower = AirportTowerController(surface)

    tower.reserve_runway(session_id=departure.session_id, runway_id="07/25", operation=RunwayOperationKind.TAKEOFF, reason="departure sequence")
    crossing = surface.request_crossing(RunwayCrossingTransaction(session_id=taxi.session_id, runway_id="07/25", reason="taxi crossing"))

    with pytest.raises(ValueError, match="already assigned"):
        surface.clear_crossing(crossing.crossing_id)


def test_departure_state_machine_requires_takeoff_clearance_before_roll() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    core.open_session(identity)
    tower = AirportTowerController(surface)
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")
    tower.start_departure(session_id=identity.session_id, runway_id="07/25")

    with pytest.raises(ValueError, match="requires takeoff clearance"):
        tower.begin_takeoff_roll(identity.session_id)

    instruction = tower.clear_takeoff(identity.session_id, reason="runway clear")
    assert instruction.semantic_action == "takeoff_clearance"
    rolled = tower.begin_takeoff_roll(identity.session_id)
    assert rolled.state is TowerDepartureState.TAKEOFF_ROLL
    airborne = tower.mark_airborne(identity.session_id)
    assert airborne.state is TowerDepartureState.AIRBORNE


def test_line_up_and_wait_does_not_imply_takeoff_clearance() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    core.open_session(identity)
    tower = AirportTowerController(surface)
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")
    tower.start_departure(session_id=identity.session_id, runway_id="07/25")

    instruction = tower.line_up_and_wait(identity.session_id, reason="sequence departure")
    assert instruction.semantic_action == "line_up_and_wait"
    with pytest.raises(ValueError, match="requires takeoff clearance"):
        tower.begin_takeoff_roll(identity.session_id)


def test_rejected_takeoff_keeps_committed_runway_protected() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    core.open_session(identity)
    tower = AirportTowerController(surface)
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")
    tower.start_departure(session_id=identity.session_id, runway_id="07/25")
    tower.clear_takeoff(identity.session_id, reason="runway clear")
    tower.begin_takeoff_roll(identity.session_id)

    rejected = tower.reject_takeoff(identity.session_id, reason="pilot rejected takeoff")
    assert rejected.state is TowerDepartureState.REJECTED_TAKEOFF
    with pytest.raises(ValueError, match="already assigned"):
        tower.reserve_runway(session_id=uuid4(), runway_id="07/25", operation=RunwayOperationKind.LANDING, reason="conflicting arrival")


def test_arrival_state_machine_releases_runway_only_when_vacated() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a2", facility_id="kutaisi")
    core.open_session(identity)
    tower = AirportTowerController(surface)
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")
    tower.start_arrival(session_id=identity.session_id, runway_id="07/25")

    instruction = tower.clear_landing(identity.session_id, reason="runway clear")
    assert instruction.semantic_action == "landing_clearance"
    attempt = tower.begin_landing_attempt(identity.session_id)
    assert attempt.state is TowerArrivalState.LANDING_ATTEMPT
    rollout = tower.mark_rollout(identity.session_id)
    assert rollout.state is TowerArrivalState.ROLLOUT

    with pytest.raises(ValueError, match="already assigned"):
        tower.reserve_runway(session_id=uuid4(), runway_id="07/25", operation=RunwayOperationKind.TAKEOFF, reason="blocked departure")

    vacated = tower.mark_runway_vacated(identity.session_id)
    assert vacated.state is TowerArrivalState.RUNWAY_VACATED


def test_go_around_releases_uncommitted_landing_reservation() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a2", facility_id="kutaisi")
    core.open_session(identity)
    tower = AirportTowerController(surface)
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")
    tower.start_arrival(session_id=identity.session_id, runway_id="07/25")
    tower.clear_landing(identity.session_id, reason="initially clear")

    state = tower.go_around(identity.session_id, reason="runway conflict detected")
    assert state.state is TowerArrivalState.GO_AROUND

    other = tower.reserve_runway(session_id=uuid4(), runway_id="07/25", operation=RunwayOperationKind.TAKEOFF, reason="runway available after go-around")
    assert other.operation is RunwayOperationKind.TAKEOFF


def test_unknown_runway_blocks_tower_reservation() -> None:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    tower = AirportTowerController(surface)

    with pytest.raises(ValueError, match="positive clearance"):
        tower.reserve_runway(session_id=uuid4(), runway_id="07/25", operation=RunwayOperationKind.TAKEOFF, reason="cannot prove runway clear")
