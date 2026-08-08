from unittest.mock import patch

from orion.jtac_runtime import JtacDesignationMethod, JtacSessionCreate, JtacSessionState, JtacSessionStore
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_command_status import MissionCommandResult, MissionCommandStatus, mission_command_statuses
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


def test_start_marking_dispatches_but_waits_for_mission_confirmation():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[_jtac()]))
    store = JtacSessionStore()
    session = store.create(JtacSessionCreate(target_id="target-1", method=JtacDesignationMethod.LASER, laser_code=1688))
    result = MissionCommandResult(command_id=session.session_id, status=MissionCommandStatus.QUEUED, message="queued")
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=result) as send:
        pending = store.start_marking(session.session_id)
    command = send.call_args.args[0]
    assert command.target_unit_id == "target-1"
    assert command.provider_unit_id == "jtac-1"
    assert command.laser_code == 1688
    assert pending.state is JtacSessionState.ASSIGNED
    assert pending.marker_active is False
    assert pending.command_id == command.command_id


def test_reconcile_acceptance_confirms_marker_active():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[_jtac()]))
    store = JtacSessionStore()
    session = store.create(JtacSessionCreate(target_id="target-1", method=JtacDesignationMethod.LASER, laser_code=1688))
    queued = MissionCommandResult(command_id=session.session_id, status=MissionCommandStatus.QUEUED, message="queued")
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=queued):
        pending = store.start_marking(session.session_id)
    mission_command_statuses.set(pending.command_id, MissionCommandStatus.ACCEPTED, "laser active")
    marking = store.reconcile(session.session_id)
    assert marking.state is JtacSessionState.MARKING
    assert marking.marker_active is True
    assert marking.laser_code == 1688


def test_reconcile_completed_closes_marker():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[_jtac()]))
    store = JtacSessionStore()
    session = store.create(JtacSessionCreate(target_id="target-1", method=JtacDesignationMethod.SMOKE))
    queued = MissionCommandResult(command_id=session.session_id, status=MissionCommandStatus.QUEUED, message="queued")
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=queued):
        pending = store.start_marking(session.session_id)
    mission_command_statuses.set(pending.command_id, MissionCommandStatus.COMPLETED, "mark complete")
    complete = store.reconcile(session.session_id)
    assert complete.state is JtacSessionState.COMPLETE
    assert complete.marker_active is False


def test_reconcile_failure_fails_session_without_claiming_marker_active():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[_jtac()]))
    store = JtacSessionStore()
    session = store.create(JtacSessionCreate(target_id="target-1", method=JtacDesignationMethod.LASER, laser_code=1688))
    queued = MissionCommandResult(command_id=session.session_id, status=MissionCommandStatus.QUEUED, message="queued")
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=queued):
        pending = store.start_marking(session.session_id)
    mission_command_statuses.set(pending.command_id, MissionCommandStatus.FAILED, "designator unavailable")
    failed = store.reconcile(session.session_id)
    assert failed.state is JtacSessionState.FAILED
    assert failed.marker_active is False
