from uuid import uuid4

import pytest

from orion.airport_surface import (
    HoldShortConstraint,
    RunwayAvailability,
    RunwayCrossingTransaction,
    RunwayState,
    SurfaceSegment,
    TaxiRoute,
)
from orion.airport_surface_runtime import AirportGroundController, AirportSurfaceCoordinator
from orion.atc_core import AtcSessionIdentity
from orion.atc_operations import FreshnessClass
from orion.atc_runtime import AtcCoreFlow


def _controller() -> tuple[AirportGroundController, AtcSessionIdentity]:
    core = AtcCoreFlow()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="viper", facility_id="kutaisi")
    core.open_session(identity)
    surface = AirportSurfaceCoordinator(core)
    controller = AirportGroundController(surface)
    controller.assume_surface_control(identity.session_id, reason="Ground owns surface movement")
    return controller, identity


def test_ground_issues_structured_taxi_route_under_surface_authority() -> None:
    controller, identity = _controller()
    route = TaxiRoute(
        session_id=identity.session_id,
        facility_id="kutaisi",
        origin="stand-12",
        destination="hold-short-07",
        segments=[SurfaceSegment(segment_id="A1", kind="taxiway", label="A")],
        runway_crossings=["07/25"],
        hold_short_resources=["07/25"],
        reason="taxi to runway",
    )

    instruction = controller.issue_taxi_route(route)

    assert instruction.semantic_action == "taxi_route"
    assert instruction.parameters["runway_crossings"] == "07/25"


def test_hold_short_is_safety_critical_and_remains_active_until_crossing_commit() -> None:
    controller, identity = _controller()
    constraint = HoldShortConstraint(
        session_id=identity.session_id,
        resource_id="07/25",
        reason="protect active runway",
    )
    instruction = controller.issue_hold_short(constraint)
    assert instruction.semantic_action == "hold_short"
    assert controller.surface.get_hold_short(identity.session_id, "07/25").active is True

    crossing = controller.request_runway_crossing(
        RunwayCrossingTransaction(
            session_id=identity.session_id,
            runway_id="07/25",
            reason="cross to departure side",
        )
    )
    controller.surface.runways.observe(
        RunwayState(
            runway_id="07/25",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="fresh geometry observation",
        )
    )
    controller.surface.clear_crossing(crossing.crossing_id)
    controller.surface.acknowledge_crossing(crossing.crossing_id)
    controller.surface.commit_crossing(crossing.crossing_id)

    assert controller.surface.get_hold_short(identity.session_id, "07/25").active is False


def test_unknown_runway_blocks_crossing_clearance() -> None:
    controller, identity = _controller()
    crossing = controller.request_runway_crossing(
        RunwayCrossingTransaction(
            session_id=identity.session_id,
            runway_id="07/25",
            reason="cross runway",
        )
    )

    with pytest.raises(ValueError, match="safe enough"):
        controller.surface.clear_crossing(crossing.crossing_id)


def test_exclusive_crossing_resource_blocks_second_aircraft() -> None:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    first = AtcSessionIdentity(mission_id="m1", aircraft_id="a1", facility_id="kutaisi")
    second = AtcSessionIdentity(mission_id="m1", aircraft_id="a2", facility_id="kutaisi")
    core.open_session(first)
    core.open_session(second)
    surface.runways.observe(
        RunwayState(
            runway_id="07/25",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="fresh observation",
        )
    )
    first_crossing = surface.request_crossing(
        RunwayCrossingTransaction(session_id=first.session_id, runway_id="07/25", reason="first crossing")
    )
    second_crossing = surface.request_crossing(
        RunwayCrossingTransaction(session_id=second.session_id, runway_id="07/25", reason="second crossing")
    )

    surface.clear_crossing(first_crossing.crossing_id)
    with pytest.raises(ValueError, match="already assigned"):
        surface.clear_crossing(second_crossing.crossing_id)


def test_completed_crossing_releases_exclusive_runway_resource() -> None:
    controller, identity = _controller()
    controller.surface.runways.observe(
        RunwayState(
            runway_id="07/25",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="fresh observation",
        )
    )
    crossing = controller.request_runway_crossing(
        RunwayCrossingTransaction(session_id=identity.session_id, runway_id="07/25", reason="cross runway")
    )
    controller.surface.clear_crossing(crossing.crossing_id)
    controller.surface.acknowledge_crossing(crossing.crossing_id)
    controller.surface.commit_crossing(crossing.crossing_id)
    completed = controller.surface.complete_crossing(crossing.crossing_id)

    assert completed.state.value == "complete"
    event_types = [event.event_type for event in controller.core.history.list(identity.session_id)]
    assert "runway_crossing_completed" in event_types
