from zipfile import ZipFile

from orion.flight_readiness import (
    FlightReadinessRequest,
    ReadinessLevel,
    evaluate_flight_readiness,
)
from orion.launch_profiles import DcsLaunchMode, DcsLaunchProfileCreate, launch_profiles
from orion.mission_preparation import PACK_ARCHIVE_PATH


def _make_active_mission(path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("mission", f"mission = {{}} -- {PACK_ARCHIVE_PATH}")
        archive.writestr(PACK_ARCHIVE_PATH, "ORION = {}")
        archive.writestr("orion/manifest.json", "{}")


def test_ready_openxr_profile_has_ui_labels(tmp_path) -> None:
    executable = tmp_path / "DCS.exe"
    executable.write_bytes(b"")
    mission = tmp_path / "Training (ORION).miz"
    _make_active_mission(mission)

    profile = launch_profiles.create(
        DcsLaunchProfileCreate(
            name="Hornet VR",
            mode=DcsLaunchMode.OPENXR,
            dcs_executable=str(executable),
            mission_path=str(mission),
        )
    )

    report = evaluate_flight_readiness(
        FlightReadinessRequest(
            profile_id=profile.profile_id,
            map_name="Persian Gulf",
            ai_ready=True,
            flight_bridge_installed=True,
            voice_ready=True,
        )
    )

    assert report.level is ReadinessLevel.READY
    assert report.ready_to_launch is True
    assert report.profile_label == "Hornet VR (OpenXR)"
    assert report.map_name == "Persian Gulf"
    assert report.ai_status == "AI готов"
    assert report.launch_plan is not None


def test_missing_executable_blocks_launch(tmp_path) -> None:
    mission = tmp_path / "Training.miz"
    _make_active_mission(mission)
    profile = launch_profiles.create(
        DcsLaunchProfileCreate(
            name="Desktop",
            mode=DcsLaunchMode.DESKTOP,
            dcs_executable=str(tmp_path / "DCS.exe"),
            mission_path=str(mission),
        )
    )

    report = evaluate_flight_readiness(
        FlightReadinessRequest(profile_id=profile.profile_id, ai_ready=True)
    )

    assert report.level is ReadinessLevel.BLOCKED
    assert report.ready_to_launch is False
    assert report.launch_plan is None


def test_missing_optional_components_gives_limited_mode(tmp_path) -> None:
    executable = tmp_path / "DCS.exe"
    executable.write_bytes(b"")
    mission = tmp_path / "Training.miz"
    with ZipFile(mission, "w") as archive:
        archive.writestr("mission", "mission = {}")

    profile = launch_profiles.create(
        DcsLaunchProfileCreate(
            name="Hornet VR",
            mode=DcsLaunchMode.OPENXR,
            dcs_executable=str(executable),
            mission_path=str(mission),
        )
    )

    report = evaluate_flight_readiness(
        FlightReadinessRequest(profile_id=profile.profile_id, ai_ready=True)
    )

    assert report.level is ReadinessLevel.LIMITED
    assert report.ready_to_launch is True
    assert any(check.key == "mission_pack" and not check.passed for check in report.checks)


def test_qwen_not_manually_started_does_not_block_dcs_launch(tmp_path) -> None:
    executable = tmp_path / "DCS.exe"
    executable.write_bytes(b"")
    mission = tmp_path / "Training (ORION).miz"
    _make_active_mission(mission)
    profile = launch_profiles.create(
        DcsLaunchProfileCreate(
            name="Desktop",
            mode=DcsLaunchMode.DESKTOP,
            dcs_executable=str(executable),
            mission_path=str(mission),
        )
    )

    report = evaluate_flight_readiness(
        FlightReadinessRequest(
            profile_id=profile.profile_id,
            ai_ready=True,
            flight_bridge_installed=True,
            voice_ready=False,
        )
    )

    assert report.level is ReadinessLevel.LIMITED
    assert report.ready_to_launch is True
    assert any(check.key == "voice" and not check.passed and not check.blocking for check in report.checks)
