from uuid import uuid4

import pytest

from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalState, ApproachType
from orion.airport_surface import RunwayAvailability, RunwayState
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import FreshnessClass


def prepared_runtime() -> tuple[AirportArrivalRuntime, object]:
    runtime = AirportArrivalRuntime()
    session_id = uuid4()
    runtime.surface.runways.observe(
        RunwayState(
            runway_id="27",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="observed clear",
        )
    )
    runtime.start(session_id=session_id, runway_id="27")
    return runtime, session_id


def advance_to_final(runtime: AirportArrivalRuntime, session_id) -> None:
    runtime.assume_arrival_control(session_id, reason="arrival identified")
    runtime.issue_descent_vectors(session_id, heading_deg=270, altitude_ft=3000, speed_kt=220, reason="vectors")
    runtime.enter_approach_control(session_id, reason="approach control")
    runtime.position_for_approach(session_id, reason="positioning")
    runtime.clear_approach(session_id, approach_type=ApproachType.ILS, altitude_ft=2000, reason="cleared approach")
    runtime.confirm_final(session_id)


def complete_tower_handoff(runtime: AirportArrivalRuntime, session_id) -> None:
    runtime.begin_tower_handoff(session_id, reason="contact tower")
    runtime.complete_tower_handoff(session_id, reason="tower contact established")


def test_normal_arrival_landing_and_ground_handoff() -> None:
    runtime, session_id = prepared_runtime()
    advance_to_final(runtime, session_id)
    complete_tower_handoff(runtime, session_id)

    runtime.clear_landing(session_id, reason="cleared to land")
    assert runtime.confirm_touchdown(session_id).state is AirportArrivalState.TOUCHDOWN
    assert runtime.confirm_rollout(session_id).state is AirportArrivalState.ROLLOUT
    assert runtime.confirm_runway_vacated(session_id).state is AirportArrivalState.RUNWAY_VACATED
    assert runtime.transfer_to_ground(session_id, reason="contact ground").state is AirportArrivalState.GROUND

    owner = runtime.core.authority.get_owner(session_id, ControllerAuthorityScope.SURFACE_MOVEMENT)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_GROUND


def test_touchdown_cannot_be_inferred_from_landing_clearance() -> None:
    runtime, session_id = prepared_runtime()
    with pytest.raises(ValueError, match="LANDING_CLEARED"):
        runtime.confirm_touchdown(session_id)


def test_ground_handoff_requires_confirmed_runway_vacated() -> None:
    runtime, session_id = prepared_runtime()
    with pytest.raises(ValueError, match="RUNWAY_VACATED"):
        runtime.transfer_to_ground(session_id, reason="too early")


def test_landing_clearance_requires_positive_runway_safety() -> None:
    runtime, session_id = prepared_runtime()
    advance_to_final(runtime, session_id)
    complete_tower_handoff(runtime, session_id)
    runtime.surface.runways.observe(
        RunwayState(
            runway_id="27",
            availability=RunwayAvailability.OCCUPIED,
            freshness=FreshnessClass.FRESH,
            reason="traffic on runway",
        )
    )
    with pytest.raises(ValueError, match="confirmed clear"):
        runtime.clear_landing(session_id, reason="unsafe")


def test_landing_clearance_rejects_stale_runway_state() -> None:
    runtime, session_id = prepared_runtime()
    advance_to_final(runtime, session_id)
    complete_tower_handoff(runtime, session_id)
    runtime.surface.runways.observe(
        RunwayState(
            runway_id="27",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.STALE,
            reason="old observation",
        )
    )
    with pytest.raises(ValueError):
        runtime.clear_landing(session_id, reason="stale runway state")


def test_go_around_from_tower_returns_flight_traffic_to_approach() -> None:
    runtime, session_id = prepared_runtime()
    advance_to_final(runtime, session_id)
    complete_tower_handoff(runtime, session_id)
    state = runtime.go_around(session_id, reason="runway conflict")
    assert state.state is AirportArrivalState.GO_AROUND
    owner = runtime.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_APPROACH
    assert runtime.enter_missed_approach(session_id, reason="missed approach").state is AirportArrivalState.MISSED_APPROACH
    assert runtime.enter_approach_control(session_id, reason="approach reacquired").state is AirportArrivalState.APPROACH_CONTROL
    assert runtime.reposition(session_id, reason="vectors for second approach").state is AirportArrivalState.REPOSITION


def test_go_around_can_complete_second_approach() -> None:
    runtime, session_id = prepared_runtime()
    advance_to_final(runtime, session_id)
    complete_tower_handoff(runtime, session_id)
    runtime.go_around(session_id, reason="runway conflict")
    runtime.enter_missed_approach(session_id, reason="missed approach")
    runtime.enter_approach_control(session_id, reason="approach reacquired")
    runtime.reposition(session_id, reason="vectors for second approach")
    runtime.issue_descent_vectors(session_id, heading_deg=270, altitude_ft=2500, reason="reposition vector")
    runtime.enter_approach_control(session_id, reason="ready for second approach")
    runtime.position_for_approach(session_id, reason="second positioning")
    runtime.clear_approach(session_id, approach_type=ApproachType.VISUAL, reason="second approach")
    runtime.confirm_final(session_id)
    complete_tower_handoff(runtime, session_id)
    runtime.clear_landing(session_id, reason="cleared to land second approach")
    runtime.confirm_touchdown(session_id)
    runtime.confirm_rollout(session_id)
    runtime.confirm_runway_vacated(session_id)
    assert runtime.transfer_to_ground(session_id, reason="contact ground").state is AirportArrivalState.GROUND


def test_supported_approach_types_are_dcs_relevant_only() -> None:
    assert set(ApproachType) == {ApproachType.ILS, ApproachType.TACAN, ApproachType.VISUAL}


def test_arrival_states_are_audit_visible() -> None:
    runtime, session_id = prepared_runtime()
    runtime.assume_arrival_control(session_id, reason="arrival")
    runtime.enter_approach_control(session_id, reason="approach")
    runtime.position_for_approach(session_id, reason="position")
    runtime.clear_approach(session_id, approach_type=ApproachType.TACAN, reason="tacan approach")
    runtime.confirm_final(session_id)
    events = runtime.core.history.list(session_id)
    states = [event.details.get("state") for event in events if event.event_type == "airport_arrival_state_changed"]
    assert "arrival_contact" in states
    assert "arrival_control" in states
    assert "approach_control" in states
    assert "approach_positioning" in states
    assert "approach" in states
    assert "final" in states
