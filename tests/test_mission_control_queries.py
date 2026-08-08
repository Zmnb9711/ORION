from orion.mission_control_queries import (
    MissionControlQuery,
    MissionControlQueryKind,
    RelativeSector,
    _angular_difference,
    _threats_in_clock_sector,
    _threats_in_relative_sector,
)
from orion.tactical_situation import TacticalThreat, TacticalThreatKind
from orion.threats import ThreatLevel


def _threat(bearing: float, *, kind: TacticalThreatKind = TacticalThreatKind.AIR, range_nm: float = 20.0, priority: float = 70.0) -> TacticalThreat:
    return TacticalThreat(
        unit_id=f"unit-{bearing}",
        name="Bandit",
        kind=kind,
        level=ThreatLevel.HIGH,
        score=70,
        bearing_deg=bearing,
        range_nm=range_nm,
        braa=f"BRAA {bearing:03.0f} for {range_nm:.1f}, 20 thousand",
        tactical_priority=priority,
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


def test_clock_sector_is_relative_to_ownship_heading():
    threats = [_threat(180), _threat(90)]
    selected = _threats_in_clock_sector(threats, hour=3, heading_deg=90)
    assert [item.bearing_deg for item in selected] == [180]


def test_relative_sectors_follow_ownship_heading():
    threats = [_threat(90), _threat(0), _threat(180)]
    assert [item.bearing_deg for item in _threats_in_relative_sector(threats, RelativeSector.AHEAD, 90)] == [90]
    assert [item.bearing_deg for item in _threats_in_relative_sector(threats, RelativeSector.LEFT, 90)] == [0]
    assert [item.bearing_deg for item in _threats_in_relative_sector(threats, RelativeSector.RIGHT, 90)] == [180]


def test_contextual_query_kinds_are_available():
    assert MissionControlQuery(kind=MissionControlQueryKind.CLOSEST_THREAT).kind is MissionControlQueryKind.CLOSEST_THREAT
    assert MissionControlQuery(kind=MissionControlQueryKind.MOST_DANGEROUS).kind is MissionControlQueryKind.MOST_DANGEROUS
    sector = MissionControlQuery(kind=MissionControlQueryKind.RELATIVE_SECTOR, sector=RelativeSector.RIGHT)
    assert sector.sector is RelativeSector.RIGHT
    assert MissionControlQuery(kind=MissionControlQueryKind.SAM_AHEAD).kind is MissionControlQueryKind.SAM_AHEAD
