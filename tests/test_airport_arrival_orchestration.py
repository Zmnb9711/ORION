from uuid import uuid4

import pytest

from orion.airport_arrival_orchestration import (
    ARRIVAL_SERVICE_STATE,
    GO_AROUND_SERVICE_STATE,
    GROUND_SERVICE_STATE,
    MISSED_APPROACH_SERVICE_STATE,
    REPOSITION_SERVICE_STATE,
    TOWER_ARRIVAL_SERVICE_STATE,
    AirportArrivalOrchestrator,
)
from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalState, ApproachType
from orion.airport_surface import RunwayAvailability, RunwayState
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import FreshnessClass
from orion.atc_service import VirtualAtcService


def _runtime():
    service = VirtualAtcService()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="hornet", facility_id="kutaisi")
    service.open_session(identity, procedural_state="arrival_contact")
    surface = AirportSurfaceCoordinator(service.core)
    surface.runways.observe(
        RunwayState(
            runway_id="07/25",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="fresh runway observation",
        )
    )
    arrival = AirportArrivalRuntime(surface)
    orchestration = AirportArrivalOrchestrator(service=service, arrival=arrival)
    return service, arrival, orchestration, identity


def _to_final():
    service, arrival, orchestration, identity = _runtime()
    orchestration.start_arrival(session_id=identity.session_id, runway_id="07/25")
    arrival.assume_arrival_control(identity.session_id, reason="radar identified")
    arrival.issue_descent_vectors(
        identity.session_id,
        heading_deg=120,
        altitude_ft=4000,
        speed_kt=250,
        reason="sequence for approach",
    )
    arrival.enter_approach_control(identity.session_id, reason="approach control active")
    arrival.position_for_approach(identity.session_id, reason="position for TACAN")
    arrival.clear_approach(
        identity.session_id,
        approach_type=ApproachType.TACAN,
        frequency="111.30",
        pressure_setting="29.92",
        reason="cleared TACAN approach",
    )
    arrival.confirm_final(identity.session_id)
    arrival.begin_tower_handoff(
        identity.session_id,
        frequency="250.000",
        reason="contact Tower",
    )
    return service, arrival, orchestration, identity


def test_arrival_orchestrator_requires_shared_core() -> None:
    service = VirtualAtcService()
    arrival = AirportArrivalRuntime()

    with pytest.raises(ValueError, match="shared ATC core"):
        AirportArrivalOrchestrator(service=service, arrival=arrival)


def test_start_arrival_claims_approach_and_updates_persistent_service_state() -> None:
    service, arrival, orchestration, identity = _runtime()

    session = orchestration.start_arrival(session_id=identity.session_id, runway_id="07/25")

    assert session.state is AirportArrivalState.ARRIVAL_CONTACT
    owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_APPROACH
    assert service.status(identity.session_id).procedural_state == ARRIVAL_SERVICE_STATE
    assert arrival.get(identity.session_id) is not None


def test_arrival_end_to_end_keeps_one_session_through_approach_tower_and_ground() -> None:
    service, arrival, orchestration, identity = _to_final()

    tower_state = orchestration.complete_approach_to_tower(
        identity.session_id,
        reason="Tower contact established",
    )
    assert tower_state.state is AirportArrivalState.TOWER
    assert service.status(identity.session_id).procedural_state == TOWER_ARRIVAL_SERVICE_STATE
    flight_owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    runway_owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.LANDING_AREA)
    assert flight_owner is not None and flight_owner.agency is ControllerAgency.AIRPORT_TOWER
    assert runway_owner is not None and runway_owner.agency is ControllerAgency.AIRPORT_TOWER

    arrival.clear_landing(identity.session_id, reason="runway clear")
    arrival.confirm_touchdown(identity.session_id)
    arrival.confirm_rollout(identity.session_id)
    arrival.confirm_runway_vacated(identity.session_id)
    ground_state = orchestration.complete_runway_vacated_to_ground(
        identity.session_id,
        reason="runway vacated, contact Ground",
    )

    assert ground_state.state is AirportArrivalState.GROUND
    assert service.status(identity.session_id).session_id == identity.session_id
    assert service.status(identity.session_id).procedural_state == GROUND_SERVICE_STATE
    surface_owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.SURFACE_MOVEMENT)
    assert surface_owner is not None and surface_owner.agency is ControllerAgency.AIRPORT_GROUND
    event_types = [event.event_type for event in service.core.history.list(identity.session_id)]
    assert "airport_arrival_service_started" in event_types
    assert "airport_arrival_tower_service_active" in event_types
    assert "airport_arrival_ground_service_active" in event_types


def test_tower_go_around_returns_flight_traffic_to_approach_and_preserves_session() -> None:
    service, arrival, orchestration, identity = _to_final()
    orchestration.complete_approach_to_tower(identity.session_id, reason="Tower contact established")
    arrival.clear_landing(identity.session_id, reason="initially runway clear")

    go_around = orchestration.go_around_to_approach(identity.session_id, reason="traffic on runway")

    assert go_around.state is AirportArrivalState.GO_AROUND
    owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_APPROACH
    assert service.status(identity.session_id).procedural_state == GO_AROUND_SERVICE_STATE

    missed = orchestration.enter_missed_approach(identity.session_id, reason="fly published missed approach")
    assert missed.state is AirportArrivalState.MISSED_APPROACH
    assert service.status(identity.session_id).procedural_state == MISSED_APPROACH_SERVICE_STATE

    reposition = orchestration.reposition(identity.session_id, reason="vector for another approach")
    assert reposition.state is AirportArrivalState.REPOSITION
    assert service.status(identity.session_id).procedural_state == REPOSITION_SERVICE_STATE
    assert service.status(identity.session_id).session_id == identity.session_id


def test_tower_handoff_cannot_be_completed_before_final_and_handoff_arm() -> None:
    _, _, orchestration, identity = _runtime()
    orchestration.start_arrival(session_id=identity.session_id, runway_id="07/25")

    with pytest.raises(ValueError, match="handoff"):
        orchestration.complete_approach_to_tower(identity.session_id, reason="too early")
