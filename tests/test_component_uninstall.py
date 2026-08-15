from pathlib import Path

import pytest

import orion.component_uninstall as model
import orion.uninstall_main as subject
from orion.component_uninstall import UninstallComponent, UninstallRequest


def test_remove_everything_expands_all_components() -> None:
    request = UninstallRequest(components={UninstallComponent.LAUNCHER}, remove_everything=True)
    assert request.components == set(UninstallComponent)
    assert request.removes_launcher
    assert request.removes_core
    assert request.removes_whisper
    assert request.removes_dcs_integration


def test_empty_selection_is_rejected() -> None:
    with pytest.raises(ValueError, match="Select at least one"):
        UninstallRequest()


def test_uninstaller_command_uses_source_module(monkeypatch) -> None:
    monkeypatch.setattr(model.sys, "frozen", False, raising=False)
    request = UninstallRequest(
        components={UninstallComponent.CORE, UninstallComponent.WHISPER},
        parent_pid=123,
    )
    command = model.uninstaller_command(request)
    assert command[1:3] == ["-m", "orion.uninstall_main"]
    assert "core,whisper" in command
    assert command[-2:] == ["--parent-pid", "123"]


def test_selective_whisper_removal_does_not_remove_runtime(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    whisper = runtime / "stt" / "whisper.cpp"
    whisper.mkdir(parents=True)
    (whisper / "whisper-cli.exe").write_bytes(b"test")
    keep = runtime / "logs" / "keep.log"
    keep.parent.mkdir(parents=True)
    keep.write_text("keep", encoding="utf-8")
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(runtime))

    subject.execute_uninstall(UninstallRequest(components={UninstallComponent.WHISPER}))

    assert not whisper.exists()
    assert keep.is_file()


def test_source_development_refuses_launcher_or_core_deletion(monkeypatch) -> None:
    monkeypatch.delenv("ORION_INSTALL_ROOT", raising=False)
    monkeypatch.setattr(subject.sys, "frozen", False, raising=False)
    with pytest.raises(RuntimeError, match="Core source files"):
        subject.execute_uninstall(UninstallRequest(components={UninstallComponent.CORE}))
    with pytest.raises(RuntimeError, match="Launcher source files"):
        subject.execute_uninstall(UninstallRequest(components={UninstallComponent.LAUNCHER}))


def test_summary_is_stable_and_user_facing() -> None:
    request = UninstallRequest(
        components={
            UninstallComponent.LAUNCHER,
            UninstallComponent.WHISPER,
            UninstallComponent.DCS_INTEGRATION,
        }
    )
    assert request.summary_lines() == [
        "Launcher",
        "Whisper runtime + medium model",
        "DCS Saved Games integration",
    ]
