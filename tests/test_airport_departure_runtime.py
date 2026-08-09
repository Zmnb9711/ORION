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


def test_lineup_requires_acknowledgement_before_physical_lineup() -> None:
    runtime, session_id = prepared_runtime()
    instruction = runtime.clear_line_up(session_id, reason="line up and wait")
    with pytest.raises(ValueError, match="acknowledged"):
        runtime.confirm_lined_up(session_id)
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    state = runtime.confirm_lined_up(session_id)
    assert state.state is AirportDepartureState.LINED_UP


def test_takeoff_roll_requires_acknowledged_takeoff_clearance() -> None:
    runtime, session_id = prepared_runtime()
    instruction = runtime.clear_takeoff(session_id, reason="cleared for takeoff")
    with pytest.raises(ValueError, match="acknowledged"):
        runtime.confirm_takeoff_roll(session_id)
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    state = runtime.confirm_takeoff_roll(session_id)
    assert state.state is AirportDepartureState.TAKEOFF_ROLL


def test_airborne_cannot_be_declared_before_takeoff_roll() -> None:
    runtime, session_id = prepared_runtime()
    with pytest.raises(ValueError, match="takeoff roll"):
        runtime.confirm_airborne(session_id)


def test_tower_to_departure_handoff_is_airborne_gated() -> None:
    runtime, session_id = prepared_runtime()
    with pytest.raises(ValueError, match="AIRBORNE"):
        runtime.begin_departure_handoff(session_id, reason="contact departure")

    instruction = runtime.clear_takeoff(session_id, reason="cleared for takeoff")
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    runtime.confirm_takeoff_roll(session_id)
    runtime.confirm_airborne(session_id)
    handoff_id = runtime.begin_departure_handoff(session_id, reason="contact departure")
    assert handoff_id is not None

    state = runtime.complete_departure_handoff(session_id)
    assert state.state is AirportDepartureState.DEPARTURE_CONTROL
    owner = runtime.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_DEPARTURE


def test_rejected_takeoff_is_only_valid_during_roll() -> None:
    runtime, session_id = prepared_runtime()
    with pytest.raises(ValueError, match="takeoff roll"):
        runtime.reject_takeoff(session_id, reason="abort")

    instruction = runtime.clear_takeoff(session_id, reason="cleared for takeoff")
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    runtime.confirm_takeoff_roll(session_id)
    state = runtime.reject_takeoff(session_id, reason="abort observed")
    assert state.state is AirportDepartureState.REJECTED_TAKEOFF


def test_departure_states_are_audit_visible() -> None:
    runtime, session_id = prepared_runtime()
    instruction = runtime.clear_takeoff(session_id, reason="cleared for takeoff")
    runtime.core.instructions.acknowledge(instruction.instruction_id)
    runtime.confirm_takeoff_roll(session_id)
    runtime.confirm_airborne(session_id)
    events = runtime.core.history.list(session_id)
    states = [event.details.get("state") for event in events if event.event_type == "airport_departure_state_changed"]
    assert "holding_point" in states
    assert "takeoff_cleared" in states
    assert "takeoff_roll" in states
    assert "airborne" in states
