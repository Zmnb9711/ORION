from orion.launch_profiles import (
    DcsLaunchMode,
    DcsLaunchProfileCreate,
    build_launch_plan,
    launch_profiles,
)


def test_openxr_launch_plan_uses_verified_arguments() -> None:
    profile = launch_profiles.create(
        DcsLaunchProfileCreate(
            name="Hornet VR",
            mode=DcsLaunchMode.OPENXR,
            dcs_executable=r"C:\Program Files\Eagle Dynamics\DCS World\bin-mt\DCS.exe",
            mission_path=r"C:\Users\Pilot\Saved Games\DCS\Missions\Test.miz",
        )
    )

    plan = build_launch_plan(profile)

    assert plan.arguments[:2] == ["--force_enable_VR", "--force_OpenXR"]
    assert plan.arguments[-1].endswith("Test.miz")
    assert plan.runtime_note is None


def test_steamvr_launch_plan_does_not_invent_runtime_switch() -> None:
    profile = launch_profiles.create(
        DcsLaunchProfileCreate(
            name="SteamVR",
            mode=DcsLaunchMode.STEAMVR,
            dcs_executable=r"D:\DCS World\bin-mt\DCS.exe",
        )
    )

    plan = build_launch_plan(profile)

    assert plan.arguments == ["--force_enable_VR"]
    assert plan.runtime_note


def test_desktop_launch_plan_has_no_vr_switches() -> None:
    profile = launch_profiles.create(
        DcsLaunchProfileCreate(
            name="Desktop",
            mode=DcsLaunchMode.DESKTOP,
            dcs_executable=r"D:\DCS World\bin-mt\DCS.exe",
        )
    )

    plan = build_launch_plan(profile)

    assert plan.arguments == []
