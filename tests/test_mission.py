import pytest
from pydantic import ValidationError

from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_store import MissionStore
from orion.support import SupportRequestCreate, SupportType


def make_unit(unit_id: str, coalition: Coalition, alive: bool = True) -> MissionUnit:
    return MissionUnit(
        unit_id=unit_id,
        name=unit_id,
        coalition=coalition,
        category=UnitCategory.AIRCRAFT,
        type_name="F-16C_50",
        position=MissionPosition(latitude=41.6, longitude=41.5, altitude_m=5000),
        heading_deg=90,
        speed_mps=220,
        alive=alive,
    )


def test_mission_store_filters_units() -> None:
    store = MissionStore()
    store.replace(
        MissionSnapshot(
            mission_id="test-mission",
            units=[
                make_unit("blue-1", Coalition.BLUE),
                make_unit("red-1", Coalition.RED),
                make_unit("red-destroyed", Coalition.RED, alive=False),
            ],
        )
    )

    assert [unit.unit_id for unit in store.units(Coalition.RED)] == ["red-1"]
    assert {unit.unit_id for unit in store.units(alive_only=False)} == {
        "blue-1",
        "red-1",
        "red-destroyed",
    }


def test_target_marking_requires_target() -> None:
    with pytest.raises(ValidationError):
        SupportRequestCreate(
            support_type=SupportType.LASER_DESIGNATION,
            requester="Enfield 1-1",
        )


def test_tanker_request_does_not_require_target() -> None:
    request = SupportRequestCreate(
        support_type=SupportType.TANKER,
        requester="Enfield 1-1",
    )
    assert request.target_unit_id is None
