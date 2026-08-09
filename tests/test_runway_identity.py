import pytest

from orion.runway_identity import (
    RunwayEndIdentity,
    RunwayIdentitySource,
    answer_runway_course,
    numeric_designator,
    reciprocal_course_deg,
    runway_number_from_magnetic_course,
)


def test_numeric_runway_designator_is_derived_from_magnetic_course() -> None:
    assert runway_number_from_magnetic_course(274.0) == 27
    assert numeric_designator(274.0) == "27"
    assert numeric_designator(94.0) == "09"


def test_north_is_runway_36_not_zero() -> None:
    assert numeric_designator(359.0) == "36"
    assert numeric_designator(1.0) == "36"


def test_reciprocal_course_and_designator_are_derived_independently() -> None:
    identity = RunwayEndIdentity(
        facility_id="batumi",
        runway_id="axis-1",
        magnetic_course_deg=274.0,
    )

    assert reciprocal_course_deg(identity.magnetic_course_deg) == 94.0
    assert identity.designator == "27"
    assert identity.reciprocal_numeric_designator == "09"
    assert identity.source is RunwayIdentitySource.DERIVED_MAGNETIC


def test_published_designator_has_priority_over_derived_number() -> None:
    identity = RunwayEndIdentity(
        facility_id="example",
        runway_id="axis-1",
        magnetic_course_deg=184.9,
        designator="18",
        source=RunwayIdentitySource.PUBLISHED,
    )

    assert identity.designator == "18"
    assert identity.source is RunwayIdentitySource.PUBLISHED


def test_parallel_suffix_is_allowed_only_when_explicitly_supplied() -> None:
    identity = RunwayEndIdentity(
        facility_id="parallel-field",
        runway_id="left-axis",
        magnetic_course_deg=90.0,
        designator="09L",
        source=RunwayIdentitySource.PUBLISHED,
    )
    assert identity.designator == "09L"

    with pytest.raises(ValueError, match="suffix"):
        RunwayEndIdentity(
            facility_id="parallel-field",
            runway_id="axis",
            magnetic_course_deg=90.0,
            designator="09X",
            source=RunwayIdentitySource.PUBLISHED,
        )


def test_runway_course_answer_returns_exact_course_not_designator_times_ten() -> None:
    identity = RunwayEndIdentity(
        facility_id="kutaisi",
        runway_id="07-end",
        magnetic_course_deg=73.4,
        true_course_deg=79.1,
        confidence=0.96,
    )

    answer = answer_runway_course(identity)

    assert answer.runway_designator == "07"
    assert answer.magnetic_course_deg == 73.4
    assert answer.magnetic_course_deg != 70.0
    assert answer.true_course_deg == 79.1
    assert answer.reciprocal_numeric_designator == "25"
    assert answer.source is RunwayIdentitySource.DERIVED_MAGNETIC
