from uuid import uuid4

from orion.aerodrome_information import AerodromeInformationSource, AerodromePressureObservation
from orion.airport_arrival_request_controller import AirportArrivalRequestController, ArrivalRequestAction
from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalState, ApproachType
from orion.airport_surface import RunwayAvailability, RunwayState
from orion.atc_operations import FreshnessClass


def _runtime() -> tuple[AirportArrivalRuntime, object, AirportArrivalRequestController]:
    runtime = AirportArrivalRuntime()
    session_id = uuid4()
    runtime.surface.runways.observe(
        RunwayState(runway_id="27", availability=RunwayAvailability.CLEAR, freshness=FreshnessClass.FRESH)
    )
    runtime.start(session_id=session_id, runway_id="27")
    return runtime, session_id, AirportArrivalRequestController(runtime)


def _to_positioning(runtime: AirportArrivalRuntime, session_id) -> None:
    runtime.assume_arrival_control(session_id, reason="arrival")
    runtime.enter_approach_control(session_id, reason="approach")
    runtime.position_for_approach(session_id, reason="position")


def test_rtb_advances_arrival_contact_to_arrival_control() -> None:
    runtime, session_id, controller = _runtime()
    result = controller.handle(session_id=session_id, text="Орион, возвращаюсь на базу")
    assert result.action is ArrivalRequestAction.ARRIVAL_CONTROL
    assert runtime.get(session_id).state is AirportArrivalState.ARRIVAL_CONTROL


def test_free_form_approach_request_clears_then_amends_active_approach() -> None:
    runtime, session_id, controller = _runtime()
    _to_positioning(runtime, session_id)
    controller.handle(session_id=session_id, text="Хочу TACAN заход")
    assert runtime.get(session_id).clearance.approach_type is ApproachType.TACAN
    controller.handle(session_id=session_id, text="Давай лучше по ILS")
    assert runtime.get(session_id).clearance.approach_type is ApproachType.ILS


def test_lower_and_vector_require_numeric_parameters_instead_of_inventing_them() -> None:
    runtime, session_id, controller = _runtime()
    runtime.assume_arrival_control(session_id, reason="arrival")
    assert controller.handle(session_id=session_id, text="Можно ниже?").action is ArrivalRequestAction.NEEDS_PARAMETER
    assert controller.handle(session_id=session_id, text="Дай курс").action is ArrivalRequestAction.NEEDS_PARAMETER
    lower = controller.handle(session_id=session_id, text="Можно ниже?", altitude_ft=3000)
    assert lower.action is ArrivalRequestAction.VECTOR_ISSUED
    vector = controller.handle(session_id=session_id, text="Дай курс", heading_deg=270)
    assert vector.action is ArrivalRequestAction.VECTOR_ISSUED


def test_information_intents_return_session_runway_and_current_qnh() -> None:
    _, session_id, controller = _runtime()
    runway = controller.handle(session_id=session_id, text="Какая полоса?")
    assert runway.action is ArrivalRequestAction.INFORMATION
    assert runway.details["runway_id"] == "27"
    qnh = controller.handle(
        session_id=session_id,
        text="Какой QNH?",
        pressure=AerodromePressureObservation(
            facility_id="TEST",
            qnh_hpa=1012.0,
            freshness=FreshnessClass.FRESH,
            source=AerodromeInformationSource.MISSION,
        ),
    )
    assert qnh.action is ArrivalRequestAction.INFORMATION
    assert qnh.details["qnh_hpa"] == 1012.0


def test_go_around_free_form_executes_runtime_transition() -> None:
    runtime, session_id, controller = _runtime()
    _to_positioning(runtime, session_id)
    runtime.clear_approach(session_id, approach_type=ApproachType.VISUAL, reason="visual")
    result = controller.handle(session_id=session_id, text="Ухожу на второй")
    assert result.action is ArrivalRequestAction.GO_AROUND
    assert runtime.get(session_id).state is AirportArrivalState.GO_AROUND
