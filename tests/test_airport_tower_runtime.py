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


def _new_tower_session(core: AtcCoreFlow, tower: AirportTowerController, aircraft_id: str) -> AtcSessionIdentity:
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id=aircraft_id, facility_id="kutaisi")
    core.open_session(identity)
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")
    return identity


def test_ground_tower_boundary_preserves_separate_authority_scopes() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="viper", facility_id="kutaisi")
    core.open_session(identity)
    ground = AirportGroundController(surface)
    tower = AirportTowerController(surface)
    ground.assume_surface_control(identity.session_id, reason="Ground owns taxi movement")
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")

    tower.record_ground_boundary_contact(identity.session_id, reason="aircraft reached holding point")

    ground_owner = core.authority.get_owner(identity.session_id, ControllerAuthorityScope.SURFACE_MOVEMENT)
    tower_owner = core.authority.get_owner(identity.session_id, ControllerAuthorityScope.LANDING_AREA)
    assert ground_owner.agency is ControllerAgency.AIRPORT_GROUND
    assert tower_owner.agency is ControllerAgency.AIRPORT_TOWER


def test_runway_reservation_requires_tower_authority() -> None:
    _, surface = _surface()
    tower = AirportTowerController(surface)

    with pytest.raises(ValueError, match="LANDING_AREA"):
        tower.reserve_runway(
            session_id=uuid4(),
            runway_id="07/25",
            operation=RunwayOperationKind.TAKEOFF,
            reason="unauthorized reservation",
        )


def test_takeoff_reservation_blocks_crossing_on_same_canonical_runway() -> None:
    core, surface = _surface()
    tower = AirportTowerController(surface)
    departure = _new_tower_session(core, tower, "a1")
    taxi = _new_tower_session(core, tower, "a2")

    tower.reserve_runway(
        session_id=departure.session_id,
        runway_id="07/25",
        operation=RunwayOperationKind.TAKEOFF,
        reason="departure sequence",
    )
    crossing = surface.request_crossing(
        RunwayCrossingTransaction(session_id=taxi.session_id, runway_id="07/25", reason="taxi crossing")
    )

    with pytest.raises(ValueError, match="already reserved"):
        surface.clear_crossing(crossing.crossing_id)


def test_departure_state_machine_requires_takeoff_clearance_before_roll() -> None:
    core, surface = _surface()
    tower = AirportTowerController(surface)
    identity = _new_tower_session(core, tower, "a1")
    tower.start_departure(session_id=identity.session_id, runway_id="07/25")

    with pytest.raises(ValueError, match="requires takeoff clearance"):
        tower.begin_takeoff_roll(identity.session_id)

    instruction = tower.clear_takeoff(identity.session_id, reason="runway clear")
    assert instruction.semantic_action == "takeoff_clearance"
    assert tower.begin_takeoff_roll(identity.session_id).state is TowerDepartureState.TAKEOFF_ROLL
    assert tower.mark_airborne(identity.session_id).state is TowerDepartureState.AIRBORNE
    assert surface.reservations.get("07/25") is None


def test_line_up_and_wait_changes_explicitly_to_takeoff() -> None:
    core, surface = _surface()
    tower = AirportTowerController(surface)
    identity = _new_tower_session(core, tower, "a1")
    tower.start_departure(session_id=identity.session_id, runway_id="07/25")

    instruction = tower.line_up_and_wait(identity.session_id, reason="sequence departure")
    assert instruction.semantic_action == "line_up_and_wait"
    with pytest.raises(ValueError, match="requires takeoff clearance"):
        tower.begin_takeoff_roll(identity.session_id)

    tower.clear_takeoff(identity.session_id, reason="departure released")
    reservation = surface.reservations.get("07/25")
    assert reservation.operation is RunwayOperationKind.TAKEOFF
    assert any(event.event_type == "runway_operation_changed" for event in core.history.list(identity.session_id))


def test_rejected_takeoff_keeps_committed_runway_protected() -> None:
    core, surface = _surface()
    tower = AirportTowerController(surface)
    identity = _new_tower_session(core, tower, "a1")
    other = _new_tower_session(core, tower, "a2")
    tower.start_departure(session_id=identity.session_id, runway_id="07/25")
    tower.clear_takeoff(identity.session_id, reason="runway clear")
    tower.begin_takeoff_roll(identity.session_id)

    rejected = tower.reject_takeoff(identity.session_id, reason="pilot rejected takeoff")
    assert rejected.state is TowerDepartureState.REJECTED_TAKEOFF
    with pytest.raises(ValueError, match="already reserved"):
        tower.reserve_runway(
            session_id=other.session_id,
            runway_id="07/25",
            operation=RunwayOperationKind.LANDING,
            reason="conflicting arrival",
        )


def test_arrival_state_machine_releases_runway_only_when_vacated() -> None:
    core, surface = _surface()
    tower = AirportTowerController(surface)
    identity = _new_tower_session(core, tower, "a2")
    other = _new_tower_session(core, tower, "a3")
    tower.start_arrival(session_id=identity.session_id, runway_id="07/25")

    assert tower.clear_landing(identity.session_id, reason="runway clear").semantic_action == "landing_clearance"
    assert tower.begin_landing_attempt(identity.session_id).state is TowerArrivalState.LANDING_ATTEMPT
    assert tower.mark_rollout(identity.session_id).state is TowerArrivalState.ROLLOUT

    with pytest.raises(ValueError, match="already reserved"):
        tower.reserve_runway(
            session_id=other.session_id,
            runway_id="07/25",
            operation=RunwayOperationKind.TAKEOFF,
            reason="blocked departure",
        )

    assert tower.mark_runway_vacated(identity.session_id).state is TowerArrivalState.RUNWAY_VACATED
    assert surface.reservations.get("07/25") is None


def test_go_around_releases_uncommitted_landing_reservation() -> None:
    core, surface = _surface()
    tower = AirportTowerController(surface)
    identity = _new_tower_session(core, tower, "a2")
    other = _new_tower_session(core, tower, "a3")
    tower.start_arrival(session_id=identity.session_id, runway_id="07/25")
    tower.clear_landing(identity.session_id, reason="initially clear")

    state = tower.go_around(identity.session_id, reason="runway conflict detected")
    assert state.state is TowerArrivalState.GO_AROUND
    reservation = tower.reserve_runway(
        session_id=other.session_id,
        runway_id="07/25",
        operation=RunwayOperationKind.TAKEOFF,
        reason="runway available after go-around",
    )
    assert reservation.operation is RunwayOperationKind.TAKEOFF


def test_unknown_runway_blocks_tower_reservation_after_authority_check() -> None:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    tower = AirportTowerController(surface)
    identity = _new_tower_session(core, tower, "a1")

    with pytest.raises(ValueError, match="positive clearance"):
        tower.reserve_runway(
            session_id=identity.session_id,
            runway_id="07/25",
            operation=RunwayOperationKind.TAKEOFF,
            reason="cannot prove runway clear",
        )
