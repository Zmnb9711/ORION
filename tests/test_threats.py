from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.threats import ThreatLevel, assess_threats, predict_position


def test_predict_position_moves_unit_forward() -> None:
    unit = MissionUnit(
        unit_id="bandit-1",
        name="Bandit 1",
        coalition=Coalition.RED,
        category=UnitCategory.AIRCRAFT,
        position=MissionPosition(latitude=41.0, longitude=41.0, altitude_m=5000),
        heading_deg=90,
        speed_mps=250,
    )

    predicted = predict_position(unit, 60)

    assert predicted.longitude > unit.position.longitude
    assert abs(predicted.latitude - unit.position.latitude) < 0.01


def test_assess_threats_filters_and_prioritises_contacts() -> None:
    snapshot = MissionSnapshot(
        mission_id="mission-1",
        units=[
            MissionUnit(
                unit_id="close-bandit",
                name="Close Bandit",
                coalition=Coalition.RED,
                category=UnitCategory.AIRCRAFT,
                position=MissionPosition(latitude=41.05, longitude=41.0, altitude_m=4000),
                heading_deg=180,
                speed_mps=280,
            ),
            MissionUnit(
                unit_id="far-bandit",
                name="Far Bandit",
                coalition=Coalition.RED,
                category=UnitCategory.GROUND,
                position=MissionPosition(latitude=42.0, longitude=41.0),
                speed_mps=0,
            ),
            MissionUnit(
                unit_id="friendly",
                name="Friendly",
                coalition=Coalition.BLUE,
                category=UnitCategory.AIRCRAFT,
                position=MissionPosition(latitude=41.01, longitude=41.0),
            ),
            MissionUnit(
                unit_id="dead-bandit",
                name="Dead Bandit",
                coalition=Coalition.RED,
                category=UnitCategory.AIRCRAFT,
                position=MissionPosition(latitude=41.01, longitude=41.0),
                alive=False,
            ),
        ],
    )

    results = assess_threats(
        snapshot=snapshot,
        own_position=MissionPosition(latitude=41.0, longitude=41.0, altitude_m=3000),
    )

    assert [item.unit_id for item in results] == ["close-bandit", "far-bandit"]
    assert results[0].score > results[1].score
    assert results[0].level in {ThreatLevel.HIGH, ThreatLevel.CRITICAL}
    assert "close proximity" in results[0].reasons
