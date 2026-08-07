from zipfile import ZipFile

import pytest

from orion.mission_activation import (
    SAFE_TRIGGER_SLOT,
    ActivationMode,
    apply_guarded_activation,
    plan_activation,
)
from orion.mission_preparation import PACK_ARCHIVE_PATH


def _write_miz(path, mission_text: str, include_pack: bool = True) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("mission", mission_text)
        if include_pack:
            archive.writestr(PACK_ARCHIVE_PATH, "ORION = {}")


def test_plan_refuses_unknown_trigger_structure(tmp_path) -> None:
    mission = tmp_path / "Unknown.miz"
    _write_miz(mission, "mission = {}")

    plan = plan_activation(str(mission))

    assert plan.mode is ActivationMode.MANUAL
    assert plan.can_apply_automatically is False
    assert "automatic editing is refused" in plan.reason
    assert any("Mission Editor" in step for step in plan.steps)


def test_guarded_activation_requires_explicit_safe_slot(tmp_path) -> None:
    mission = tmp_path / "Safe.miz"
    _write_miz(mission, f"mission = {{}}\n{SAFE_TRIGGER_SLOT}\n")

    plan = plan_activation(str(mission))
    assert plan.mode is ActivationMode.GUARDED
    assert plan.can_apply_automatically is True

    result = apply_guarded_activation(str(mission))
    assert result.mode is ActivationMode.ALREADY_ACTIVE

    with ZipFile(mission, "r") as archive:
        text = archive.read("mission").decode("utf-8")
        assert SAFE_TRIGGER_SLOT not in text
        assert "ORION Mission Pack activation" in text


def test_activation_fails_when_pack_is_not_embedded(tmp_path) -> None:
    mission = tmp_path / "NoPack.miz"
    _write_miz(mission, f"mission = {{}}\n{SAFE_TRIGGER_SLOT}\n", include_pack=False)

    with pytest.raises(ValueError, match="not embedded"):
        apply_guarded_activation(str(mission))
