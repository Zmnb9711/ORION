from uuid import uuid4

import pytest

from orion.airport_atc_orchestration import AirportAtcOrchestrator
from orion.airport_surface import RunwayAvailability, RunwayState
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.airport_tower_runtime import AirportTowerController
from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import FreshnessClass
from orion.atc_service import VirtualAtcService


def _runtime():
    service = VirtualAtcService()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="viper", facility_id="kutaisi")
    service.open_session(identity, procedural_state="tower_departure")
    surface = AirportSurfaceCoordinator(service.core)
    surface.runways.observe(
        RunwayState(
            runway_id="07/25",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="fresh runway observation",
        )
    )
    tower = AirportTowerController(surface)
    tower.assume_runway_control(identity.session_id, reason="Tower owns runway")
    tower.start_departure(session_id=identity.session_id, runway_id="07/25")
    orchestrator = AirportAtcOrchestrator(service=service, tower=tower)
    orchestrator.assume_tower_local_traffic(identity.session_id, reason="Tower owns local departure traffic")
    return service, tower, orchestrator, identity


def test_departure_handoff_cannot_be_armed_without_tower_flight_traffic_authority() -> None:
    service = VirtualAtcService()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    service.open_session(identity, procedural_state="tower_departure")
    surface = AirportSurfaceCoordinator(service.core)
    tower = AirportTowerController(surface)
    orchestrator = AirportAtcOrchestrator(service=service, tower=tower)

    with pytest.raises(ValueError, match="FLIGHT_TRAFFIC"):
        orchestrator.arm_tower_to_departure(identity.session_id, reason="prepare departure handoff")


def test_airborne_gate_blocks_premature_tower_to_departure_transfer() -> None:
    service, _, orchestrator, identity = _runtime()
    orchestrator.arm_tower_to_departure(identity.session_id, reason="departure ready")

    with pytest.raises(ValueError, match="AIRBORNE"):
        orchestrator.complete_tower_to_departure_on_airborne(identity.session_id, reason="too early")

    owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner.agency is ControllerAgency.AIRPORT_TOWER


def test_airborne_event_transfers_flight_traffic_to_departure() -> None:
    service, tower, orchestrator, identity = _runtime()
    handoff = orchestrator.arm_tower_to_departure(
        identity.session_id,
        reason="departure controller available",
        frequency="250.000",
    )
    tower.clear_takeoff(identity.session_id, reason="runway clear")
    tower.begin_takeoff_roll(identity.session_id)
    tower.mark_airborne(identity.session_id)

    completed = orchestrator.complete_tower_to_departure_on_airborne(
        identity.session_id,
        reason="airborne confirmed",
        contact_established=False,
    )

    assert completed.handoff_id == handoff.handoff_id
    owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner.agency is ControllerAgency.AIRPORT_DEPARTURE
    landing_area = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.LANDING_AREA)
    assert landing_area.agency is ControllerAgency.AIRPORT_TOWER
    event_types = [event.event_type for event in service.core.history.list(identity.session_id)]
    assert "airport_departure_authority_transferred" in event_types


def test_duplicate_departure_handoff_arm_is_rejected() -> None:
    _, _, orchestrator, identity = _runtime()
    orchestrator.arm_tower_to_departure(identity.session_id, reason="first handoff")

    with pytest.raises(ValueError, match="already armed"):
        orchestrator.arm_tower_to_departure(identity.session_id, reason="duplicate handoff")


def test_orchestrator_requires_shared_atc_core() -> None:
    service = VirtualAtcService()
    surface = AirportSurfaceCoordinator()
    tower = AirportTowerController(surface)

    with pytest.raises(ValueError, match="shared ATC core"):
        AirportAtcOrchestrator(service=service, tower=tower)
