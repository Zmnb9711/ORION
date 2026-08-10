from orion.airport_arrival_requests import ArrivalRequestIntent, amend_clearance, classify_arrival_request
from orion.airport_arrival_runtime import ApproachType, ArrivalClearance


def test_free_form_arrival_requests_cover_ru_and_en() -> None:
    assert classify_arrival_request("Орион, давай лучше по ILS").intent is ArrivalRequestIntent.REQUEST_ILS
    assert classify_arrival_request("Хочу TACAN заход").intent is ArrivalRequestIntent.REQUEST_TACAN
    assert classify_arrival_request("Давай визуально").intent is ArrivalRequestIntent.REQUEST_VISUAL
    assert classify_arrival_request("Полосу не вижу").intent is ArrivalRequestIntent.REPORT_RUNWAY_NOT_IN_SIGHT
    assert classify_arrival_request("Можно еще снизиться?").intent is ArrivalRequestIntent.REQUEST_LOWER
    assert classify_arrival_request("Дай курс на полосу").intent is ArrivalRequestIntent.REQUEST_VECTOR
    assert classify_arrival_request("Ухожу на второй").intent is ArrivalRequestIntent.GO_AROUND
    assert classify_arrival_request("going around").intent is ArrivalRequestIntent.GO_AROUND


def test_clearance_amendment_preserves_unspecified_fields() -> None:
    initial = ArrivalClearance(
        runway_id="27",
        approach_type=ApproachType.TACAN,
        heading_deg=270,
        altitude_ft=2500,
        speed_kt=220,
        direct_to="IAF",
        frequency="251.000",
        pressure_setting="QNH 1013",
    )
    amended = amend_clearance(initial, approach_type=ApproachType.ILS, altitude_ft=1800)
    assert amended.approach_type is ApproachType.ILS
    assert amended.altitude_ft == 1800
    assert amended.heading_deg == 270
    assert amended.speed_kt == 220
    assert amended.direct_to == "IAF"
    assert amended.frequency == "251.000"
    assert amended.pressure_setting == "QNH 1013"
