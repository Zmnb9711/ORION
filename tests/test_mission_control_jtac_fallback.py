from unittest.mock import patch
from uuid import uuid4

from orion.jtac_runtime import JtacDesignationMethod, JtacSessionState, jtac_sessions
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_command_status import MissionCommandResult, MissionCommandStatus, mission_command_statuses
from orion.mission_control_jtac import MissionControlJtacRequest, orchestrate_jtac
from orion.mission_store import mission_store


def _ground_jtac() -> MissionUnit:
    return MissionUnit(
        unit_id="jtac-ground",
        name="JTAC Alpha",
        coalition=Coalition.BLUE,
        category=UnitCategory.GROUND,
        type_name="HMMWV",
        position=MissionPosition(latitude=0, longitude=0),
    )


def _apache() -> MissionUnit:
    return MissionUnit(
        unit_id="apache-1",
        name="Gunship 11",
        coalition=Coalition.BLUE,
        category=UnitCategory.HELICOPTER,
        type_name="AH-64D",
        position=MissionPosition(latitude=0, longitude=0),
    )


def setup_function() -> None:
    jtac_sessions.reset()
    mission_store.replace(MissionSnapshot(mission_id="mission-fallback", units=[_ground_jtac(), _apache()]))


def _queued() -> MissionCommandResult:
    return MissionCommandResult(command_id=uuid4(), status=MissionCommandStatus.QUEUED, message="queued")


def test_failed_designator_is_reassigned_to_next_compatible_asset() -> None:
    with patch("orion.jtac_runtime.mission_bridge.send", side_effect=[_queued(), _queued()]), patch(
        "orion.mission_control_jtac.submit_jtac_voice"
    ), patch("orion.mission_control_jtac._submit_orchestration_voice") as announce:
        first = orchestrate_jtac(
            MissionControlJtacRequest(target_id="sam-1", method=JtacDesignationMethod.LASER, laser_code=1688, language="ru")
        )
        assert first.session is not None
        assert first.session.assigned_asset_id == "jtac-ground"
        mission_command_statuses.set(first.session.command_id, MissionCommandStatus.FAILED, "designator lost")

    sessions = jtac_sessions.list()
    assert len(sessions) == 2
    replacement = next(item for item in sessions if item.session_id != first.session.session_id)
    assert replacement.state is JtacSessionState.ASSIGNED
    assert replacement.assigned_asset_id == "apache-1"
    assert replacement.target_id == "sam-1"
    assert replacement.laser_code == 1688
    assert replacement.command_id is not None
    assert replacement.command_id != first.session.command_id
    assert announce.called
    assert "переназначен" in announce.call_args.args[0]


def test_fallback_respects_max_attempts() -> None:
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=_queued()), patch(
        "orion.mission_control_jtac.submit_jtac_voice"
    ), patch("orion.mission_control_jtac._submit_orchestration_voice") as announce:
        first = orchestrate_jtac(MissionControlJtacRequest(target_id="sam-1", max_attempts=1, language="en"))
        assert first.session is not None
        mission_command_statuses.set(first.session.command_id, MissionCommandStatus.FAILED, "lost")

    sessions = jtac_sessions.list()
    assert len(sessions) == 1
    assert sessions[0].state is JtacSessionState.FAILED
    assert announce.called
    assert "No backup designators" in announce.call_args.args[0]


def test_smoke_does_not_fallback_to_laser_only_aircraft() -> None:
    with patch("orion.jtac_runtime.mission_bridge.send", return_value=_queued()), patch(
        "orion.mission_control_jtac.submit_jtac_voice"
    ), patch("orion.mission_control_jtac._submit_orchestration_voice") as announce:
        first = orchestrate_jtac(
            MissionControlJtacRequest(target_id="target-2", method=JtacDesignationMethod.SMOKE, smoke_color="red")
        )
        assert first.session is not None
        assert first.session.assigned_asset_id == "jtac-ground"
        mission_command_statuses.set(first.session.command_id, MissionCommandStatus.FAILED, "smoke unavailable")

    sessions = jtac_sessions.list()
    assert len(sessions) == 1
    assert sessions[0].state is JtacSessionState.FAILED
    assert announce.called
