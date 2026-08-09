from uuid import uuid4

import pytest

from orion.airport_surface import RunwayAvailability, RunwayCrossingTransaction, RunwayState
from orion.airport_surface_runtime import AirportGroundController, AirportSurfaceCoordinator
from orion.airport_tower_runtime import AirportTowerController, RunwayOperationKind
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


def test_ground_to_tower_boundary_handoff_is_acknowledgement_gated() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="viper", facility_id="kutaisi")
    core.open_session(identity)
    ground = AirportGroundController(surface)
    tower = AirportTowerController(surface)
    ground.assume_surface_control(identity.session_id, reason="Ground owns taxi movement")
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")

    handoff_id = tower.begin_ground_boundary_handoff(identity.session_id, reason="aircraft reached holding point")
    assert core.authority.get_owner(identity.session_id, ControllerAuthorityScope.SURFACE_MOVEMENT).agency is ControllerAgency.AIRPORT_GROUND

    tower.complete_ground_boundary_handoff(handoff_id)
    assert core.authority.get_owner(identity.session_id, ControllerAuthorityScope.SURFACE_MOVEMENT).agency is ControllerAgency.AIRPORT_TOWER


def test_takeoff_reservation_blocks_crossing_on_same_runway() -> None:
    core, surface = _surface()
    departure = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    taxi = AtcSessionIdentity(mission_id="m1", aircraft_id="a2", facility_id="kutaisi")
    core.open_session(departure)
    core.open_session(taxi)
    tower = AirportTowerController(surface)

    tower.reserve_runway(
        session_id=departure.session_id,
        runway_id="07/25",
        operation=RunwayOperationKind.TAKEOFF,
        reason="departure sequence",
    )
    crossing = surface.request_crossing(
        RunwayCrossingTransaction(session_id=taxi.session_id, runway_id="07/25", reason="taxi crossing")
    )

    with pytest.raises(ValueError, match="already assigned"):
        surface.clear_crossing(crossing.crossing_id)


def test_crossing_reservation_blocks_landing_on_same_runway() -> None:
    core, surface = _surface()
    crossing_session = AtcSessionIdentity(mission_id="m1", aircraft_id="truck", facility_id="kutaisi")
    arrival = AtcSessionIdentity(mission_id="m1", aircraft_id="a2", facility_id="kutaisi")
    core.open_session(crossing_session)
    core.open_session(arrival)
    crossing = surface.request_crossing(
        RunwayCrossingTransaction(
            session_id=crossing_session.session_id,
            runway_id="07/25",
            reason="cross active runway",
        )
    )
    surface.clear_crossing(crossing.crossing_id)
    tower = AirportTowerController(surface)

    with pytest.raises(ValueError, match="already assigned"):
        tower.reserve_runway(
            session_id=arrival.session_id,
            runway_id="07/25",
            operation=RunwayOperationKind.LANDING,
            reason="arrival final",
        )


def test_takeoff_clearance_requires_tower_landing_area_authority() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    core.open_session(identity)
    tower = AirportTowerController(surface)
    reservation = tower.reserve_runway(
        session_id=identity.session_id,
        runway_id="07/25",
        operation=RunwayOperationKind.TAKEOFF,
        reason="ready for departure",
    )

    with pytest.raises(ValueError, match="required authority"):
        tower.issue_takeoff_clearance(reservation.reservation_id)

    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")
    instruction = tower.issue_takeoff_clearance(reservation.reservation_id)
    assert instruction.semantic_action == "takeoff_clearance"
    assert instruction.parameters["runway_id"] == "07/25"


def test_unknown_runway_blocks_tower_reservation() -> None:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    core.open_session(identity)
    tower = AirportTowerController(surface)

    with pytest.raises(ValueError, match="positive clearance"):
        tower.reserve_runway(
            session_id=identity.session_id,
            runway_id="07/25",
            operation=RunwayOperationKind.TAKEOFF,
            reason="cannot prove runway clear",
        )


def test_committed_runway_operation_cannot_be_normally_released() -> None:
    core, surface = _surface()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    core.open_session(identity)
    tower = AirportTowerController(surface)
    reservation = tower.reserve_runway(
        session_id=identity.session_id,
        runway_id="07/25",
        operation=RunwayOperationKind.TAKEOFF,
        reason="takeoff roll",
    )
    tower.commit_reservation(reservation.reservation_id)

    with pytest.raises(ValueError, match="Committed runway operation"):
        tower.release_reservation(reservation.reservation_id)
