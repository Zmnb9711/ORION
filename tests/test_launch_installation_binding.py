from pathlib import Path

import pytest

from orion.dcs_installations import (
    DcsInstallationCreate,
    DcsInstallationUpdate,
    dcs_installations,
)
from orion.launch_profiles import (
    DcsLaunchMode,
    DcsLaunchProfileCreate,
    build_launch_plan,
    launch_profiles,
)


def test_launch_profile_resolves_registered_installation(tmp_path: Path) -> None:
    executable = tmp_path / "DCS.exe"
    executable.write_bytes(b"")
    installation = dcs_installations.create(
        DcsInstallationCreate(name="Custom DCS", executable_path=str(executable))
    )
    profile = launch_profiles.create(
        DcsLaunchProfileCreate(
            name="Hornet VR",
            mode=DcsLaunchMode.OPENXR,
            installation_id=installation.installation_id,
        )
    )

    plan = build_launch_plan(profile)

    assert plan.executable == str(executable)
    assert plan.arguments[:2] == ["--force_enable_VR", "--force_OpenXR"]


def test_profile_follows_changed_installation_path(tmp_path: Path) -> None:
    first = tmp_path / "first" / "DCS.exe"
    first.parent.mkdir()
    first.write_bytes(b"")
    installation = dcs_installations.create(
        DcsInstallationCreate(name="Movable DCS", executable_path=str(first))
    )
    profile = launch_profiles.create(
        DcsLaunchProfileCreate(name="VR", installation_id=installation.installation_id)
    )

    second = tmp_path / "second" / "DCS.exe"
    second.parent.mkdir()
    second.write_bytes(b"")
    updated = dcs_installations.update(
        installation.installation_id,
        DcsInstallationUpdate(executable_path=str(second)),
    )

    assert updated is not None
    assert updated.exists is True
    assert build_launch_plan(profile).executable == str(second)


def test_profile_rejects_unknown_installation() -> None:
    from uuid import uuid4

    with pytest.raises(KeyError, match="installation"):
        launch_profiles.create(
            DcsLaunchProfileCreate(name="Broken", installation_id=uuid4())
        )
