from uuid import uuid4

import pytest

from orion.airport_arrival_reports import AirportArrivalReportController, RunwaySightAction
from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalState, ApproachType
from orion.airport_surface import RunwayAvailability, RunwayState
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import FreshnessClass


def _visual_runtime() -> tuple[AirportArrivalRuntime, object]:
    runtime = AirportArrivalRuntime()
    session_id = uuid4()
    runtime.surface.runways.observe(
        RunwayState(
            runway_id="27",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="clear",
        )
    )
    runtime.start(session_id=session_id, runway_id="27")
    runtime.assume_arrival_control(session_id, reason="arrival")
    runtime.enter_approach_control(session_id, reason="approach")
    runtime.position_for_approach(session_id, reason="position")
    runtime.clear_approach(session_id, approach_type=ApproachType.VISUAL, reason="visual approach")
    return runtime, session_id


def _handoff_to_tower(runtime: AirportArrivalRuntime, session_id) -> None:
    runtime.confirm_final(session_id)
    runtime.begin_tower_handoff(session_id, reason="contact tower")
    runtime.complete_tower_handoff(session_id, reason="tower contact")


def test_runway_in_sight_allows_visual_to_continue_without_state_jump() -> None:
    runtime, session_id = _visual_runtime()
    report = AirportArrivalReportController(runtime).report_runway_in_sight(session_id)
    assert report.action is RunwaySightAction.CONTINUE_VISUAL
    assert runtime.get(session_id).state is AirportArrivalState.APPROACH


def test_runway_not_in_sight_on_visual_requests_reposition_or_instrument() -> None:
    runtime, session_id = _visual_runtime()
    report = AirportArrivalReportController(runtime).report_runway_not_in_sight(session_id)
    assert report.action is RunwaySightAction.REPOSITION_OR_INSTRUMENT
    assert runtime.get(session_id).state is AirportArrivalState.APPROACH


def test_runway_not_in_sight_on_visual_after_tower_handoff_orders_go_around() -> None:
    runtime, session_id = _visual_runtime()
    _handoff_to_tower(runtime, session_id)

    report = AirportArrivalReportController(runtime).report_runway_not_in_sight(session_id)

    assert report.action is RunwaySightAction.GO_AROUND
    assert runtime.get(session_id).state is AirportArrivalState.GO_AROUND
    owner = runtime.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_APPROACH


def test_runway_not_in_sight_after_landing_clearance_orders_go_around() -> None:
    runtime, session_id = _visual_runtime()
    _handoff_to_tower(runtime, session_id)
    runtime.clear_landing(session_id, reason="cleared to land")

    report = AirportArrivalReportController(runtime).report_runway_not_in_sight(session_id)

    assert report.action is RunwaySightAction.GO_AROUND
    assert runtime.get(session_id).state is AirportArrivalState.GO_AROUND
    owner = runtime.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_APPROACH


def test_runway_sight_report_rejected_before_approach_phase() -> None:
    runtime = AirportArrivalRuntime()
    session_id = uuid4()
    runtime.start(session_id=session_id, runway_id="27")
    with pytest.raises(ValueError, match="not valid"):
        AirportArrivalReportController(runtime).report_runway_in_sight(session_id)


def test_runway_sight_report_is_audited() -> None:
    runtime, session_id = _visual_runtime()
    AirportArrivalReportController(runtime).report_runway_in_sight(session_id, reason="visual acquired")
    events = runtime.core.history.list(session_id)
    matches = [event for event in events if event.event_type == "airport_arrival_runway_sight_report"]
    assert matches
    assert matches[-1].details["runway_in_sight"] is True
    assert matches[-1].details["action"] == RunwaySightAction.CONTINUE_VISUAL.value
    assert matches[-1].source_agency is ControllerAgency.AIRPORT_APPROACH


def test_tower_runway_sight_report_is_audited_as_tower() -> None:
    runtime, session_id = _visual_runtime()
    _handoff_to_tower(runtime, session_id)
    AirportArrivalReportController(runtime).report_runway_in_sight(session_id, reason="visual maintained")
    events = runtime.core.history.list(session_id)
    matches = [event for event in events if event.event_type == "airport_arrival_runway_sight_report"]
    assert matches[-1].source_agency is ControllerAgency.AIRPORT_TOWER
