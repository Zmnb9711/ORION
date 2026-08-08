from unittest.mock import patch
from uuid import uuid4

from orion.jtac_runtime import JtacDesignationMethod, JtacSessionCreate, JtacSessionState, jtac_sessions
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_command_status import MissionCommandResult, MissionCommandStatus, mission_command_statuses
from orion.mission_control_jtac_cancel import cancel_jtac
from orion.mission_control_runtime import MissionControlPicture
from orion.mission_store import mission_store
from orion.tactical_situation import TacticalThreat, TacticalThreatKind
from orion.threats import ThreatLevel


def _jtac() -> MissionUnit:
    return MissionUnit(unit_id="jtac-1", name="JTAC Alpha", coalition=Coalition.BLUE, category=UnitCategory.GROUND, type_name="HMMWV", position=MissionPosition(latitude=0, longitude=0))


def _target(unit_id: str, *, alive: bool = True) -> MissionUnit:
    return MissionUnit(unit_id=unit_id, name=unit_id, coalition=Coalition.RED, category=UnitCategory.GROUND, type_name="SAM", alive=alive, position=MissionPosition(latitude=0.1, longitude=0.1))


def setup_function() -> None:
    jtac_sessions.reset()
    mission_store.replace(MissionSnapshot(mission_id="cancel-retask", units=[_jtac(), _target("old"), _target("new")]))


def test_cancel_waits_for_mission_side_completion() -> None:
    session = jtac_sessions.create(JtacSessionCreate(target_id="old", method=JtacDesignationMethod.LASER, laser_code=1688))
    queued = MissionCommandResult(command_id=uuid4(), status=MissionCommandStatus.QUEUED, message="queued")
    with patch("orion.mission_control_jtac_cancel.mission_bridge.send", return_value=queued) as send:
        result = cancel_jtac(session.session_id)
    assert result.accepted is True
    command = send.call_args.args[0]
    assert command.command.value == "stop_laser"
    assert jtac_sessions.get(session.session_id).state is JtacSessionState.ASSIGNED

    mission_command_statuses.set(result.cancel_command_id, MissionCommandStatus.COMPLETED, "stopped")
    assert jtac_sessions.get(session.session_id).state is JtacSessionState.CANCELLED


def test_target_loss_schedules_stop_before_retask() -> None:
    session = jtac_sessions.create(JtacSessionCreate(target_id="old", method=JtacDesignationMethod.LASER, laser_code=1688))
    threat = TacticalThreat(unit_id="new", name="New SAM", kind=TacticalThreatKind.SAM, level=ThreatLevel.HIGH, score=90, bearing_deg=10, range_nm=8, braa="010/8")
    picture = MissionControlPicture(primary_surface_threat=threat, total_threats=1)
    cancel_result = type("Cancel", (), {"accepted": True, "cancel_command_id": uuid4()})()

    with patch("orion.mission_control_jtac_retask.build_mission_control_picture", return_value=picture), patch("orion.mission_control_jtac_retask.cancel_jtac", return_value=cancel_result) as cancel:
        mission_store.replace(MissionSnapshot(mission_id="cancel-retask", units=[_jtac(), _target("new")]))
    cancel.assert_called_once_with(session.session_id)
