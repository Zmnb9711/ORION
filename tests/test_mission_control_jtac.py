from unittest.mock import patch
from uuid import UUID

from orion.jtac_runtime import JtacDesignationMethod, JtacSessionState, jtac_sessions
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_bridge import MissionCommandType
from orion.mission_command_status import MissionCommandResult, MissionCommandStatus
from orion.mission_control_jtac import JtacTargetMode, MissionControlJtacRequest, orchestrate_jtac
from orion.mission_control_runtime import MissionControlPicture
from orion.mission_store import mission_store
from orion.tactical_situation import TacticalThreat, TacticalThreatKind
from orion.threats import ThreatLevel


def _jtac() -> MissionUnit:
    return MissionUnit(unit_id="jtac-1", name="JTAC Alpha", coalition=Coalition.BLUE, category=UnitCategory.GROUND, type_name="HMMWV", position=MissionPosition(latitude=0, longitude=0))


def _queued() -> MissionCommandResult:
    return MissionCommandResult(command_id=UUID(int=1), status=MissionCommandStatus.QUEUED, message="queued")


def setup_function() -> None:
    jtac_sessions.reset()
    mission_store.replace(MissionSnapshot(mission_id="mission-56", units=[_jtac()]))


def test_explicit_laser_request_runs_assignment_and_dispatch() -> None:
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=_queued()) as send, patch("orion.mission_control_jtac.submit_jtac_voice"):
        result = orchestrate_jtac(MissionControlJtacRequest(target_id="sam-1", method=JtacDesignationMethod.LASER, laser_code=1688, language="ru"))
    assert result.accepted is True
    assert result.session is not None
    assert result.session.state is JtacSessionState.ASSIGNED
    assert result.session.assigned_asset_id == "jtac-1"
    assert result.session.command_id is not None
    assert "1688" in result.spoken_text
    command = send.call_args.args[0]
    assert command.command is MissionCommandType.LASER
    assert command.target_unit_id == "sam-1"
    assert command.provider_unit_id == "jtac-1"
    assert command.laser_code == 1688


def test_primary_surface_threat_can_be_selected_automatically() -> None:
    threat = TacticalThreat(unit_id="sam-primary", name="SA-11", kind=TacticalThreatKind.SAM, level=ThreatLevel.HIGH, score=90, bearing_deg=20, range_nm=15, braa="020/15")
    picture = MissionControlPicture(primary_surface_threat=threat, total_threats=1)
    with patch("orion.mission_control_jtac.build_mission_control_picture", return_value=picture), patch("orion.jtac_runtime.mission_bridge.send", return_value=_queued()), patch("orion.mission_control_jtac.submit_jtac_voice"):
        result = orchestrate_jtac(MissionControlJtacRequest(target_mode=JtacTargetMode.PRIMARY_SURFACE_THREAT, language="en"))
    assert result.accepted is True
    assert result.target_id == "sam-primary"
    assert result.target_name == "SA-11"
    assert "SA-11" in result.spoken_text
    assert "1688" in result.spoken_text


def test_no_surface_threat_returns_clean_negative_result() -> None:
    with patch("orion.mission_control_jtac.build_mission_control_picture", return_value=MissionControlPicture()):
        result = orchestrate_jtac(MissionControlJtacRequest(target_mode=JtacTargetMode.PRIMARY_SURFACE_THREAT, language="ru"))
    assert result.accepted is False
    assert result.session is None
    assert "не найдена" in result.spoken_text


def test_smoke_request_does_not_send_laser_code() -> None:
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=_queued()) as send, patch("orion.mission_control_jtac.submit_jtac_voice"):
        result = orchestrate_jtac(MissionControlJtacRequest(target_id="target-2", method=JtacDesignationMethod.SMOKE, smoke_color="orange"))
    assert result.accepted is True
    command = send.call_args.args[0]
    assert command.command is MissionCommandType.SMOKE
    assert command.laser_code is None
    assert command.smoke_color == "orange"
