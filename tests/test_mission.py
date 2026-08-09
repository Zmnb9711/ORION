from unittest.mock import patch

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


def test_replace_notifies_jtac_and_proactive_observers_once() -> None:
    store = MissionStore()
    snapshot = MissionSnapshot(mission_id="mission-events")
    with patch.object(store, "_notify_jtac_target_changes") as jtac, patch.object(
        store, "_notify_proactive_mission_control"
    ) as proactive:
        returned = store.replace(snapshot)
    assert returned is snapshot
    assert store.get() is snapshot
    jtac.assert_called_once_with(snapshot)
    proactive.assert_called_once_with(snapshot)


def test_snapshot_is_stored_before_proactive_observer_runs() -> None:
    store = MissionStore()
    snapshot = MissionSnapshot(mission_id="mission-visible")
    observed: list[MissionSnapshot | None] = []

    def observe(current: MissionSnapshot) -> None:
        assert current is snapshot
        observed.append(store.get())

    with patch.object(store, "_notify_jtac_target_changes"), patch.object(
        store, "_notify_proactive_mission_control", side_effect=observe
    ):
        store.replace(snapshot)
    assert observed == [snapshot]


def test_each_snapshot_replacement_emits_one_proactive_event() -> None:
    store = MissionStore()
    first = MissionSnapshot(mission_id="mission-1", mission_time_s=10)
    second = MissionSnapshot(mission_id="mission-1", mission_time_s=11)
    with patch.object(store, "_notify_jtac_target_changes"), patch.object(
        store, "_notify_proactive_mission_control"
    ) as proactive:
        store.replace(first)
        store.replace(second)
    assert proactive.call_count == 2
    assert proactive.call_args_list[0].args == (first,)
    assert proactive.call_args_list[1].args == (second,)


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
