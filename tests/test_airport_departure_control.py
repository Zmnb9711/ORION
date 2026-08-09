from uuid import uuid4

import pytest

from orion.airport_departure_control import AirportDepartureController, DepartureClearance, DepartureRoute
from orion.atc_core import AtcCore, ControllerAgency, ControllerAuthorityScope


def prepared_controller() -> tuple[AirportDepartureController, object]:
    core = AtcCore()
    session_id = uuid4()
    core.claim_authority(
        session_id=session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.AIRPORT_DEPARTURE,
        reason="handoff complete",
    )
    return AirportDepartureController(core), session_id


def test_departure_clearance_requires_departure_authority() -> None:
    core = AtcCore()
    controller = AirportDepartureController(core)
    with pytest.raises(ValueError, match="Departure must own"):
        controller.issue_clearance(uuid4(), DepartureClearance(heading_deg=270), reason="initial")


def test_issue_initial_departure_clearance() -> None:
    controller, session_id = prepared_controller()
    clearance = DepartureClearance(
        heading_deg=270,
        altitude_ft=8000,
        direct_to="DAGLI",
        frequency_mhz=251.0,
        qnh_hpa=1012,
    )
    instruction = controller.issue_clearance(session_id, clearance, reason="initial departure")
    assert instruction.parameters["heading_deg"] == 270
    assert instruction.parameters["altitude_ft"] == 8000
    assert instruction.parameters["direct_to"] == "DAGLI"
    assert controller.current_clearance(session_id) == clearance


def test_departure_clearance_amendment_preserves_unspecified_fields() -> None:
    controller, session_id = prepared_controller()
    controller.issue_clearance(
        session_id,
        DepartureClearance(heading_deg=270, altitude_ft=8000, frequency_mhz=251.0),
        reason="initial",
    )
    controller.amend_clearance(session_id, DepartureClearance(heading_deg=310), reason="vector amendment")
    current = controller.current_clearance(session_id)
    assert current is not None
    assert current.heading_deg == 310
    assert current.altitude_ft == 8000
    assert current.frequency_mhz == 251.0


def test_known_sid_route_is_represented_without_fabrication() -> None:
    controller, session_id = prepared_controller()
    route = DepartureRoute(name="DAGLI ONE", fixes=["DAGLI", "KUMRU"], transition_fix="KUMRU")
    instruction = controller.issue_clearance(session_id, DepartureClearance(route=route), reason="known procedure")
    assert instruction.parameters["route_name"] == "DAGLI ONE"
    assert instruction.parameters["route_fixes"] == "DAGLI,KUMRU"
    assert instruction.parameters["transition_fix"] == "KUMRU"


def test_free_form_queries_never_invent_unknown_values() -> None:
    controller, session_id = prepared_controller()
    controller.issue_clearance(session_id, DepartureClearance(altitude_ft=6000), reason="initial")
    assert controller.answer(session_id, "какой курс после взлета?") == "No assigned heading is recorded."
    assert controller.answer(session_id, "до какой высоты набирать?") == "Cleared altitude 6000 feet."
    assert controller.answer(session_id, "какое давление поставить?") == "No reliable pressure setting is recorded."


def test_standard_pressure_answer_is_explicit() -> None:
    controller, session_id = prepared_controller()
    controller.issue_clearance(session_id, DepartureClearance(standard_pressure=True), reason="above transition")
    assert "1013.25" in controller.answer(session_id, "pressure?")
