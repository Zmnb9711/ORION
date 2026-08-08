from orion.application_state import get_application_state
from orion.flight_runtime_summary import get_flight_runtime_summary


def test_flight_runtime_summary_contract_is_available():
    summary = get_flight_runtime_summary()
    assert summary.friendly_count >= 0
    assert summary.hostile_count >= 0
    assert summary.support.awacs_available >= 0
    assert summary.support.tankers_available >= 0
    assert summary.support.jtac_available >= 0
    assert summary.aar.phase is not None


def test_application_state_includes_flight_runtime():
    state = get_application_state()
    assert state.flight is not None
    assert state.flight.threats.hostile_count == state.flight.hostile_count
    assert isinstance(state.flight.agents.active, list)
    assert isinstance(state.flight.agents.queued, list)
