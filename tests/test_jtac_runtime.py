from unittest.mock import patch

from orion.jtac_runtime import JtacDesignationMethod, JtacSessionCreate, JtacSessionState, JtacSessionStore
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_command_status import MissionCommandResult, MissionCommandStatus
from orion.mission_store import mission_store


def _jtac():
    return MissionUnit(unit_id="jtac-1", name="JTAC Alpha", coalition=Coalition.BLUE, category=UnitCategory.GROUND, type_name="HMMWV", position=MissionPosition(latitude=0, longitude=0))


def test_create_auto_assigns_available_friendly_jtac():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[_jtac()]))
    store = JtacSessionStore()
    session = store.create(JtacSessionCreate(target_id="target-1", method=JtacDesignationMethod.LASER, laser_code=1688))
    assert session.state is JtacSessionState.ASSIGNED
    assert session.assigned_asset_id == "jtac-1"


def test_create_fails_when_no_designator_is_available():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[]))
    store = JtacSessionStore()
    session = store.create(JtacSessionCreate(target_id="target-1", method=JtacDesignationMethod.SMOKE))
    assert session.state is JtacSessionState.FAILED


def test_start_marking_dispatches_laser_through_mission_bridge():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[_jtac()]))
    store = JtacSessionStore()
    session = store.create(JtacSessionCreate(target_id="target-1", method=JtacDesignationMethod.LASER, laser_code=1688))
    result = MissionCommandResult(command_id=session.session_id, status=MissionCommandStatus.QUEUED, message="queued")
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=result) as send:
        marking = store.start_marking(session.session_id)
    command = send.call_args.args[0]
    assert command.target_unit_id == "target-1"
    assert command.provider_unit_id == "jtac-1"
    assert command.laser_code == 1688
    assert marking.state is JtacSessionState.MARKING
    assert marking.marker_active is True
    assert marking.command_id == command.command_id
