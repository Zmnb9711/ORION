from orion.mission_control_queries import (
    MissionControlQuery,
    MissionControlQueryKind,
    _angular_difference,
)


def test_clock_sector_angular_difference_wraps_across_zero():
    assert _angular_difference(355, 0) == 5
    assert _angular_difference(5, 0) == 5


def test_clock_query_requires_valid_hour():
    query = MissionControlQuery(kind=MissionControlQueryKind.CLOCK_SECTOR, clock_hour=3)
    assert query.clock_hour == 3


def test_picture_query_defaults_to_english_without_voice():
    query = MissionControlQuery(kind=MissionControlQueryKind.PICTURE)
    assert query.language == "en"
    assert query.speak is False
