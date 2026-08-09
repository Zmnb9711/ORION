from uuid import uuid4

import pytest

from orion.aerodrome_information import AerodromeInformationSource, AerodromePressureObservation
from orion.airport_departure_control import (
    AirportDepartureController,
    DepartureClearance,
    DeparturePressureContext,
    DepartureRoute,
)
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import FreshnessClass
from orion.atc_runtime import AtcCoreFlow


def prepared_controller() -> tuple[AirportDepartureController, object]:
    core = AtcCoreFlow()
    session_id = uuid4()
    core.claim_authority(
        session_id=session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.AIRPORT_DEPARTURE,
        reason="handoff complete",
    )
    return AirportDepartureController(core), session_id


def test_departure_clearance_requires_departure_authority() -> None:
    core = AtcCoreFlow()
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
        DepartureClearance(heading_deg=270, altitude_ft=8000, frequency_mhz=251.0, standard_pressure=True),
        reason="initial",
    )
    controller.amend_clearance(session_id, DepartureClearance(heading_deg=310), reason="vector amendment")
    current = controller.current_clearance(session_id)
    assert current is not None
    assert current.heading_deg == 310
    assert current.altitude_ft == 8000
    assert current.frequency_mhz == 251.0
    assert current.standard_pressure is True


def test_empty_departure_amendment_is_rejected() -> None:
    controller, session_id = prepared_controller()
    controller.issue_clearance(session_id, DepartureClearance(altitude_ft=5000), reason="initial")
    with pytest.raises(ValueError, match="amendment"):
        controller.amend_clearance(session_id, DepartureClearance(), reason="empty")


def test_known_sid_route_is_represented_without_fabrication() -> None:
    controller, session_id = prepared_controller()
    route = DepartureRoute(name="DAGLI ONE", fixes=["DAGLI", "KUMRU"], transition_fix="KUMRU")
    instruction = controller.issue_clearance(session_id, DepartureClearance(route=route), reason="known procedure")
    assert instruction.parameters["route_name"] == "DAGLI ONE"
    assert instruction.parameters["route_fixes"] == "DAGLI,KUMRU"
    assert instruction.parameters["transition_fix"] == "KUMRU"


def test_pressure_decision_uses_shared_aerodrome_information() -> None:
    controller, _ = prepared_controller()
    pressure = AerodromePressureObservation(
        facility_id="KOBULETI",
        qnh_hpa=1009.0,
        freshness=FreshnessClass.FRESH,
        source=AerodromeInformationSource.DCS,
    )
    context = DeparturePressureContext(transition_altitude_ft=6000, transition_level=70)
    below = controller.pressure_clearance(altitude_ft=5000, pressure=pressure, context=context)
    above = controller.pressure_clearance(altitude_ft=7000, pressure=pressure, context=context)
    assert below.qnh_hpa == 1009.0
    assert below.standard_pressure is False
    assert above.standard_pressure is True
    assert above.qnh_hpa is None


def test_stale_pressure_is_not_used_for_positive_answer() -> None:
    controller, _ = prepared_controller()
    pressure = AerodromePressureObservation(
        facility_id="KOBULETI",
        qnh_hpa=1009.0,
        freshness=FreshnessClass.STALE,
        source=AerodromeInformationSource.DCS,
    )
    result = controller.pressure_clearance(
        altitude_ft=3000,
        pressure=pressure,
        context=DeparturePressureContext(transition_altitude_ft=6000),
    )
    assert result.parameters() == {}


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
