from unittest.mock import patch

from orion.jtac_runtime import JtacDesignationMethod, JtacSessionCreate, JtacSessionState, jtac_sessions
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_command_status import MissionCommandResult, MissionCommandStatus, mission_command_statuses
from orion.mission_store import mission_store


def _jtac():
    return MissionUnit(unit_id="jtac-1", name="JTAC Alpha", coalition=Coalition.BLUE, category=UnitCategory.GROUND, type_name="HMMWV", position=MissionPosition(latitude=0, longitude=0))


def _armed_session(language: str = "ru"):
    jtac_sessions.reset()
    mission_store.replace(MissionSnapshot(mission_id="m", units=[_jtac()]))
    session = jtac_sessions.create(JtacSessionCreate(target_id="target-1", method=JtacDesignationMethod.LASER, laser_code=1688), language=language)
    queued = MissionCommandResult(command_id=session.session_id, status=MissionCommandStatus.QUEUED, message="queued")
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=queued):
        session = jtac_sessions.start_marking(session.session_id)
    return session


def test_accepted_status_auto_marks_and_announces_laser_code():
    session = _armed_session("ru")
    with patch("orion.jtac_status_observer.submit_jtac_voice") as voice:
        mission_command_statuses.set(session.command_id, MissionCommandStatus.ACCEPTED, "laser active")
    updated = jtac_sessions.get(session.session_id)
    assert updated is not None
    assert updated.state is JtacSessionState.MARKING
    assert updated.marker_active is True
    voice.assert_called_once()
    announced, language = voice.call_args.args
    assert announced.laser_code == 1688
    assert language == "ru"


def test_completed_status_auto_completes_and_announces():
    session = _armed_session("en")
    mission_command_statuses.set(session.command_id, MissionCommandStatus.ACCEPTED, "laser active")
    with patch("orion.jtac_status_observer.submit_jtac_voice") as voice:
        mission_command_statuses.set(session.command_id, MissionCommandStatus.COMPLETED, "mark complete")
    updated = jtac_sessions.get(session.session_id)
    assert updated is not None
    assert updated.state is JtacSessionState.COMPLETE
    assert updated.marker_active is False
    voice.assert_called_once()


def test_failed_status_auto_fails_and_announces():
    session = _armed_session("ru")
    with patch("orion.jtac_status_observer.submit_jtac_voice") as voice:
        mission_command_statuses.set(session.command_id, MissionCommandStatus.FAILED, "designator lost")
    updated = jtac_sessions.get(session.session_id)
    assert updated is not None
    assert updated.state is JtacSessionState.FAILED
    assert updated.marker_active is False
    voice.assert_called_once()
