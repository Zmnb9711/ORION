from pathlib import Path

from orion.active_dcs_installation import ActiveDcsInstallation, ActiveDcsInstallationStore
from orion.dcs_installations import DcsInstallationType
from orion.launch_profiles import DcsLaunchProfile, DcsLaunchMode, build_launch_plan


def test_launch_profile_can_resolve_from_active_installation(monkeypatch, tmp_path):
    store = ActiveDcsInstallationStore(tmp_path / "active.json")
    store.set(
        ActiveDcsInstallation(
            installation_type=DcsInstallationType.STEAM,
            executable_path=r"D:\SteamLibrary\steamapps\common\DCSWorld\bin\DCS.exe",
            saved_games_path=r"C:\Users\Pilot\Saved Games\DCS",
        )
    )
    monkeypatch.setattr("orion.launch_profiles.active_dcs_installation", store)
    profile = DcsLaunchProfile(name="VR", mode=DcsLaunchMode.OPENXR, use_active_installation=True)
    plan = build_launch_plan(profile)
    assert plan.executable.endswith(r"DCSWorld\bin\DCS.exe")
    assert "--force_OpenXR" in plan.arguments


def test_explicit_executable_overrides_active_installation(monkeypatch, tmp_path):
    store = ActiveDcsInstallationStore(tmp_path / "active.json")
    store.set(
        ActiveDcsInstallation(
            installation_type=DcsInstallationType.STEAM,
            executable_path=r"D:\Steam\DCSWorld\bin\DCS.exe",
        )
    )
    monkeypatch.setattr("orion.launch_profiles.active_dcs_installation", store)
    profile = DcsLaunchProfile(
        name="Manual",
        mode=DcsLaunchMode.DESKTOP,
        dcs_executable=r"E:\CustomDCS\bin\DCS.exe",
        use_active_installation=True,
    )
    assert build_launch_plan(profile).executable == r"E:\CustomDCS\bin\DCS.exe"
