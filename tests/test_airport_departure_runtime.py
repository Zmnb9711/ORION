from uuid import uuid4

import pytest

from orion.airport_departure_runtime import AirportDepartureRuntime, AirportDepartureState
from orion.airport_surface import RunwayAvailability, RunwayState
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import FreshnessClass


def prepared_runtime() -> tuple[AirportDepartureRuntime, object]:
    runtime = AirportDepartureRuntime()
    session_id = uuid4()
    runtime.tower.assume_runway_control(session_id, reason="departure")
    runtime.surface.runways.observe(RunwayState(runway_id="27", availability=RunwayAvailability.CLEAR, freshness=FreshnessClass.FRESH, reason="observed clear"))
    runtime.start(session_id=session_id, runway_id="27")
    return runtime, session_id


def test_lineup_requires_acknowledgement_before_physical_lineup() -> None:
    runtime, session_id = prepared_runtime()
    instruction = runtime.clear_line_up(session_id, reason="line up and wait")
    with pytest.raises(ValueError, match="acknowledged"):
        runtime.confirm_lined_up(session_id)
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    assert runtime.confirm_lined_up(session_id).state is AirportDepartureState.LINED_UP


def test_takeoff_roll_requires_acknowledged_takeoff_clearance() -> None:
    runtime, session_id = prepared_runtime()
    instruction = runtime.clear_takeoff(session_id, reason="cleared for takeoff")
    with pytest.raises(ValueError, match="acknowledged"):
        runtime.confirm_takeoff_roll(session_id)
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    assert runtime.confirm_takeoff_roll(session_id).state is AirportDepartureState.TAKEOFF_ROLL


def test_airborne_cannot_be_declared_before_takeoff_roll() -> None:
    runtime, session_id = prepared_runtime()
    with pytest.raises(ValueError, match="takeoff roll"):
        runtime.confirm_airborne(session_id)


def test_tower_to_departure_handoff_is_airborne_gated_and_idempotent() -> None:
    runtime, session_id = prepared_runtime()
    with pytest.raises(ValueError, match="AIRBORNE"):
        runtime.begin_departure_handoff(session_id, reason="contact departure")
    instruction = runtime.clear_takeoff(session_id, reason="cleared for takeoff")
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    runtime.confirm_takeoff_roll(session_id)
    runtime.confirm_airborne(session_id)
    handoff_id = runtime.begin_departure_handoff(session_id, reason="contact departure")
    assert runtime.begin_departure_handoff(session_id, reason="duplicate observation") == handoff_id
    state = runtime.complete_departure_handoff(session_id)
    assert state.state is AirportDepartureState.DEPARTURE_CONTROL
    assert runtime.complete_departure_handoff(session_id).state is AirportDepartureState.DEPARTURE_CONTROL
    owner = runtime.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_DEPARTURE


def test_traffic_hold_requires_explicit_release_before_clearance() -> None:
    runtime, session_id = prepared_runtime()
    assert runtime.hold_for_traffic(session_id, reason="landing traffic").state is AirportDepartureState.HOLDING_FOR_TRAFFIC
    with pytest.raises(ValueError):
        runtime.clear_takeoff(session_id, reason="cleared")
    assert runtime.resume_from_traffic_hold(session_id, reason="traffic clear").state is AirportDepartureState.HOLDING_POINT


def test_takeoff_clearance_can_be_cancelled_only_before_roll() -> None:
    runtime, session_id = prepared_runtime()
    runtime.clear_takeoff(session_id, reason="cleared for takeoff")
    state = runtime.cancel_takeoff_clearance(session_id, reason="landing traffic")
    assert state.state is AirportDepartureState.TAKEOFF_CLEARANCE_CANCELLED
    assert runtime.return_to_holding_point(session_id, reason="hold short").state is AirportDepartureState.HOLDING_POINT

    instruction = runtime.clear_takeoff(session_id, reason="cleared again")
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    runtime.confirm_takeoff_roll(session_id)
    with pytest.raises(ValueError, match="cancelled before takeoff roll"):
        runtime.cancel_takeoff_clearance(session_id, reason="too late")


def test_rejected_takeoff_keeps_runway_occupied_until_vacated() -> None:
    runtime, session_id = prepared_runtime()
    instruction = runtime.clear_takeoff(session_id, reason="cleared for takeoff")
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    runtime.confirm_takeoff_roll(session_id)
    assert runtime.reject_takeoff(session_id, reason="abort observed").state is AirportDepartureState.REJECTED_TAKEOFF
    assert runtime.confirm_stopped_on_runway(session_id).state is AirportDepartureState.STOPPED_ON_RUNWAY
    assert runtime.surface.reservations.get("27") is not None
    assert runtime.confirm_runway_vacated_after_abort(session_id).state is AirportDepartureState.RUNWAY_VACATED_AFTER_ABORT
    assert runtime.surface.reservations.get("27") is None


def test_rejected_takeoff_is_only_valid_during_roll() -> None:
    runtime, session_id = prepared_runtime()
    with pytest.raises(ValueError, match="takeoff roll"):
        runtime.reject_takeoff(session_id, reason="abort")


def test_departure_states_are_audit_visible() -> None:
    runtime, session_id = prepared_runtime()
    instruction = runtime.clear_takeoff(session_id, reason="cleared for takeoff")
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    runtime.confirm_takeoff_roll(session_id)
    runtime.reject_takeoff(session_id, reason="abort")
    runtime.confirm_stopped_on_runway(session_id)
    runtime.confirm_runway_vacated_after_abort(session_id)
    events = runtime.core.history.list(session_id)
    states = [event.details.get("state") for event in events if event.event_type == "airport_departure_state_changed"]
    assert "holding_point" in states
    assert "takeoff_cleared" in states
    assert "takeoff_roll" in states
    assert "rejected_takeoff" in states
    assert "stopped_on_runway" in states
    assert "runway_vacated_after_abort" in states
