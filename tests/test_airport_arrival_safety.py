from uuid import uuid4

from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalState, ApproachType
from orion.airport_arrival_safety import AirportArrivalSafetyController, ArrivalSafetyAction
from orion.airport_surface import RunwayAvailability, RunwayState
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import FreshnessClass


def _runtime_on_final() -> tuple[AirportArrivalRuntime, object]:
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
    runtime.clear_approach(session_id, approach_type=ApproachType.TACAN, reason="cleared approach")
    runtime.confirm_final(session_id)
    return runtime, session_id


def _tower(runtime: AirportArrivalRuntime, session_id) -> None:
    runtime.begin_tower_handoff(session_id, reason="contact tower")
    runtime.complete_tower_handoff(session_id, reason="tower contact")


def test_safety_withholds_clearance_before_tower_when_runway_unknown() -> None:
    runtime, session_id = _runtime_on_final()
    runtime.surface.runways.observe(
        RunwayState(
            runway_id="27",
            availability=RunwayAvailability.UNKNOWN,
            freshness=FreshnessClass.UNKNOWN,
            reason="no reliable observation",
        )
    )
    decision = AirportArrivalSafetyController(runtime).enforce(session_id)
    assert decision.action is ArrivalSafetyAction.WITHHOLD_LANDING_CLEARANCE
    assert runtime.get(session_id).state is AirportArrivalState.FINAL


def test_safety_withholds_landing_clearance_under_tower_while_runway_occupied() -> None:
    runtime, session_id = _runtime_on_final()
    _tower(runtime, session_id)
    runtime.surface.runways.observe(
        RunwayState(
            runway_id="27",
            availability=RunwayAvailability.OCCUPIED,
            freshness=FreshnessClass.FRESH,
            reason="traffic on runway",
        )
    )
    decision = AirportArrivalSafetyController(runtime).enforce(session_id, reason="runway conflict")
    assert decision.action is ArrivalSafetyAction.WITHHOLD_LANDING_CLEARANCE
    assert runtime.get(session_id).state is AirportArrivalState.TOWER


def test_safety_orders_go_around_after_landing_clearance_if_runway_becomes_unsafe() -> None:
    runtime, session_id = _runtime_on_final()
    _tower(runtime, session_id)
    runtime.clear_landing(session_id, reason="cleared to land")
    runtime.surface.runways.observe(
        RunwayState(
            runway_id="27",
            availability=RunwayAvailability.OCCUPIED,
            freshness=FreshnessClass.FRESH,
            reason="runway incursion",
        )
    )
    decision = AirportArrivalSafetyController(runtime).enforce(session_id, reason="runway incursion")
    assert decision.action is ArrivalSafetyAction.GO_AROUND
    assert runtime.get(session_id).state is AirportArrivalState.GO_AROUND
    owner = runtime.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_APPROACH


def test_safety_allows_continue_when_runway_is_fresh_and_clear() -> None:
    runtime, session_id = _runtime_on_final()
    decision = AirportArrivalSafetyController(runtime).evaluate(session_id)
    assert decision.action is ArrivalSafetyAction.CONTINUE
