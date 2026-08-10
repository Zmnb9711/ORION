from uuid import uuid4

import pytest

from orion.aerodrome_information import AerodromeInformationSource, AerodromePressureObservation
from orion.airport_arrival_information import AirportArrivalInformationController, ArrivalInformationKind
from orion.airport_arrival_requests import ArrivalRequestIntent
from orion.airport_arrival_runtime import AirportArrivalRuntime
from orion.atc_operations import FreshnessClass


def test_arrival_information_answers_assigned_runway() -> None:
    runtime = AirportArrivalRuntime()
    session_id = uuid4()
    runtime.start(session_id=session_id, runway_id="27")
    controller = AirportArrivalInformationController(runtime)

    answer = controller.answer(session_id=session_id, intent=ArrivalRequestIntent.REQUEST_ACTIVE_RUNWAY)

    assert answer.kind is ArrivalInformationKind.ASSIGNED_RUNWAY
    assert answer.data["runway_id"] == "27"
    assert "27" in answer.text_en
    assert "27" in answer.text_ru


def test_arrival_information_answers_current_qnh() -> None:
    runtime = AirportArrivalRuntime()
    session_id = uuid4()
    runtime.start(session_id=session_id, runway_id="27")
    controller = AirportArrivalInformationController(runtime)
    pressure = AerodromePressureObservation(
        facility_id="Kobuleti",
        qnh_hpa=1008.4,
        freshness=FreshnessClass.FRESH,
        source=AerodromeInformationSource.DCS,
    )

    answer = controller.answer(
        session_id=session_id,
        intent=ArrivalRequestIntent.REQUEST_QNH,
        pressure=pressure,
    )

    assert answer.kind is ArrivalInformationKind.QNH
    assert answer.data["qnh_hpa"] == 1008.4
    assert answer.data["source"] == "dcs"
    assert "1008" in answer.text_en
    assert "1008" in answer.text_ru


def test_arrival_information_refuses_stale_qnh() -> None:
    runtime = AirportArrivalRuntime()
    session_id = uuid4()
    runtime.start(session_id=session_id, runway_id="27")
    controller = AirportArrivalInformationController(runtime)
    pressure = AerodromePressureObservation(
        facility_id="Kobuleti",
        qnh_hpa=1008.4,
        freshness=FreshnessClass.STALE,
        source=AerodromeInformationSource.DCS,
    )

    with pytest.raises(ValueError, match="positively known"):
        controller.answer(
            session_id=session_id,
            intent=ArrivalRequestIntent.REQUEST_QNH,
            pressure=pressure,
        )
