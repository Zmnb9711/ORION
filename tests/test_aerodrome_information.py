from datetime import UTC, datetime

import pytest

from orion.aerodrome_information import (
    AerodromeInformationSource,
    AerodromePressureObservation,
    STANDARD_PRESSURE_HPA,
    answer_aerodrome_pressure,
    hpa_to_inhg,
    hpa_to_mmhg,
)
from orion.atc_operations import FreshnessClass


def test_qnh_is_default_pressure_answer_with_common_units() -> None:
    observation = AerodromePressureObservation(
        facility_id="batumi",
        qnh_hpa=1008.0,
        freshness=FreshnessClass.FRESH,
        source=AerodromeInformationSource.DCS,
    )

    answer = answer_aerodrome_pressure(observation)

    assert answer.qnh_hpa == 1008.0
    assert answer.qnh_inhg == pytest.approx(hpa_to_inhg(1008.0))
    assert answer.qnh_mmhg == pytest.approx(hpa_to_mmhg(1008.0))
    assert answer.qfe_hpa is None
    assert answer.is_current_enough is True


def test_qfe_can_be_runway_specific_without_replacing_qnh() -> None:
    observation = AerodromePressureObservation(
        facility_id="kutaisi",
        qnh_hpa=1016.0,
        qfe_hpa=995.4,
        runway_designator="07",
        freshness=FreshnessClass.AGING,
        source=AerodromeInformationSource.MISSION,
        confidence=0.9,
    )

    answer = answer_aerodrome_pressure(observation)

    assert answer.qnh_hpa == 1016.0
    assert answer.qfe_hpa == 995.4
    assert answer.runway_designator == "07"
    assert answer.qfe_inhg == pytest.approx(hpa_to_inhg(995.4))
    assert answer.qfe_mmhg == pytest.approx(hpa_to_mmhg(995.4))
    assert answer.confidence == 0.9


def test_runway_specific_pressure_requires_qfe() -> None:
    with pytest.raises(ValueError, match="requires QFE"):
        AerodromePressureObservation(
            facility_id="kutaisi",
            qnh_hpa=1010.0,
            runway_designator="25",
            freshness=FreshnessClass.FRESH,
            source=AerodromeInformationSource.DCS,
        )


def test_stale_pressure_is_returned_but_marked_not_current_enough() -> None:
    observation = AerodromePressureObservation(
        facility_id="senaki",
        qnh_hpa=1002.0,
        observed_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        freshness=FreshnessClass.STALE,
        source=AerodromeInformationSource.METAR,
    )

    answer = answer_aerodrome_pressure(observation)

    assert answer.qnh_hpa == 1002.0
    assert answer.is_current_enough is False
    assert answer.freshness is FreshnessClass.STALE


def test_standard_pressure_is_a_distinct_constant_not_default_qnh() -> None:
    observation = AerodromePressureObservation(
        facility_id="batumi",
        qnh_hpa=1001.0,
        freshness=FreshnessClass.FRESH,
        source=AerodromeInformationSource.ATIS,
    )

    answer = answer_aerodrome_pressure(observation)

    assert STANDARD_PRESSURE_HPA == 1013.25
    assert answer.qnh_hpa != STANDARD_PRESSURE_HPA
