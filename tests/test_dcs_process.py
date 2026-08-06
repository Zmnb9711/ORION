from uuid import uuid4

import pytest

from orion.dcs_process import DcsProcessManager, ProcessState
from orion.launch_profiles import DcsLaunchMode, DcsLaunchPlan


class FakeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.exit_code = None

    def poll(self):
        return self.exit_code


def _plan() -> DcsLaunchPlan:
    return DcsLaunchPlan(
        executable="C:/DCS/bin-mt/DCS.exe",
        arguments=["--force_enable_VR", "--force_OpenXR", "Mission.miz"],
        working_directory="C:/DCS/bin-mt",
        mode=DcsLaunchMode.OPENXR,
        mission_path="Mission.miz",
    )


def test_launch_records_pid_and_arguments() -> None:
    process = FakeProcess()
    manager = DcsProcessManager(launcher=lambda plan: process)
    profile_id = uuid4()

    record = manager.launch(profile_id, _plan())

    assert record.pid == 4321
    assert record.profile_id == profile_id
    assert record.arguments[:2] == ["--force_enable_VR", "--force_OpenXR"]
    assert record.state is ProcessState.STARTED


def test_duplicate_running_profile_is_rejected() -> None:
    manager = DcsProcessManager(launcher=lambda plan: FakeProcess())
    profile_id = uuid4()
    manager.launch(profile_id, _plan())

    with pytest.raises(RuntimeError, match="already running"):
        manager.launch(profile_id, _plan())


def test_process_exit_is_detected() -> None:
    process = FakeProcess()
    manager = DcsProcessManager(launcher=lambda plan: process)
    record = manager.launch(uuid4(), _plan())
    process.exit_code = 0

    refreshed = manager.get(record.launch_id)

    assert refreshed is not None
    assert refreshed.state is ProcessState.EXITED
    assert refreshed.exit_code == 0
