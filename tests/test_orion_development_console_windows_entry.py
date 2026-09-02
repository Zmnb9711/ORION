from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.orion_development_console import windows_entry


def _repository(tmp_path: Path, *, runtime: bool = True) -> Path:
    repository = tmp_path / "ORION"
    (repository / ".git").mkdir(parents=True)
    (repository / "tools" / "orion_development_console").mkdir(parents=True)
    (repository / "branding").mkdir()
    (repository / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (repository / "tools" / "orion_development_console" / "__main__.py").write_text(
        "", encoding="utf-8"
    )
    (repository / "branding" / "orion.ico").write_bytes(b"icon")
    if runtime:
        pythonw = repository / windows_entry.VENV_PYTHONW
        pythonw.parent.mkdir(parents=True)
        pythonw.write_bytes(b"runtime")
    return repository


def test_repository_resolution_is_independent_of_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert windows_entry.resolve_repository(repository) == repository.resolve()
    assert (
        windows_entry.resolve_repository(
            entry_path=repository / "tools" / "orion_development_console" / "windows_entry.py"
        )
        == repository.resolve()
    )


def test_missing_or_incomplete_repository_is_a_visible_launch_error(tmp_path: Path) -> None:
    messages: list[str] = []

    result = windows_entry.main(
        ["--repository", str(tmp_path / "missing")],
        error_presenter=messages.append,
        ui_runner=lambda _repository: pytest.fail("UI must not run"),
    )

    assert result == 1
    assert messages and windows_entry.APP_TITLE in messages[0]
    assert "repository is unavailable" in messages[0]


def test_runtime_resolution_is_bounded_to_project_venv(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    assert windows_entry.resolve_runtime(repository) == (
        repository / ".venv" / "Scripts" / "pythonw.exe"
    ).resolve()


def test_missing_runtime_is_visible_and_does_not_repair_environment(tmp_path: Path) -> None:
    repository = _repository(tmp_path, runtime=False)
    messages: list[str] = []

    result = windows_entry.main(
        ["--repository", str(repository)],
        error_presenter=messages.append,
        ui_runner=lambda _repository: pytest.fail("UI must not run"),
    )

    assert result == 1
    assert "Python runtime is unavailable" in messages[0]
    assert not (repository / ".venv").exists()


def test_entry_invokes_only_existing_console_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    launched: list[Path] = []
    monkeypatch.setattr(sys, "path", [path for path in sys.path if path != str(repository.resolve())])

    result = windows_entry.main(
        ["--repository", str(repository)],
        error_presenter=lambda message: pytest.fail(message),
        ui_runner=launched.append,
    )

    assert result == 0
    assert launched == [repository.resolve()]
    assert sys.path[0] == str(repository.resolve())


def test_entry_has_dev_identity_and_no_product_lifecycle_imports() -> None:
    source = Path(windows_entry.__file__).read_text(encoding="utf-8")
    assert windows_entry.APP_TITLE == "ORION Development Console"
    assert "tools.orion_development_console.ui" in source
    for forbidden in (
        "orion.core_main",
        "orion.launcher_main",
        "orion.dcs",
        "orion.srs",
        "provider",
        "microphone",
        "packaging",
    ):
        assert forbidden not in source.casefold()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcut COM is Windows-only")
def test_shortcut_creator_targets_pythonw_without_touching_desktop(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    script = (
        Path(__file__).parents[1]
        / "tools"
        / "orion_development_console"
        / "create_windows_shortcut.ps1"
    )
    entry_source = Path(windows_entry.__file__)
    destination_entry = repository / "tools" / "orion_development_console" / "windows_entry.py"
    destination_entry.write_text(entry_source.read_text(encoding="utf-8"), encoding="utf-8")
    shortcut_path = tmp_path / "ORION Development Console.lnk"

    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Repository",
            str(repository),
            "-ShortcutPath",
            str(shortcut_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert shortcut_path.is_file()
    inspect_environment = dict(os.environ)
    inspect_environment["ORION_TEST_SHORTCUT"] = str(shortcut_path)
    inspect = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:ORION_TEST_SHORTCUT); "
            'Write-Output $s.TargetPath; Write-Output $s.Arguments; '
            "Write-Output $s.WorkingDirectory; Write-Output $s.IconLocation",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
        env=inspect_environment,
    ).stdout
    assert r"ORION\.venv\Scripts\pythonw.exe" in inspect
    assert r"ORION\tools\orion_development_console\windows_entry.py" in inspect
    assert '--repository "' in inspect
    assert r"ORION\branding\orion.ico" in inspect


def test_existing_console_retains_title_branding_and_all_phase_actions() -> None:
    repository = Path(__file__).parents[1]
    ui_source = (repository / "tools" / "orion_development_console" / "ui.py").read_text(
        encoding="utf-8"
    )
    theme_source = (
        repository / "tools" / "orion_development_console" / "theme.py"
    ).read_text(encoding="utf-8")
    assert 'self.root.title("ORION Development Console")' in ui_source
    assert 'repository_root / "branding" / "orion.ico"' in theme_source
    for label in (
        "OVERVIEW",
        "ROADMAP · PHASE 3",
        "HISTORY",
        "GUARD",
        "EVIDENCE",
        "SYSTEM",
        "ПРОВЕРИТЬ ВСЁ",
        "ВСПОМНИТЬ ВСЁ",
        "ЗАПИСАТЬ ИСТОРИЮ",
        "ПРОДОЛЖИТЬ РАЗРАБОТКУ",
        "ОБНОВИТЬ",
    ):
        assert label.casefold() in ui_source.casefold() or label.casefold() in (
            repository / "tools" / "orion_development_console" / "roadmap_view.py"
        ).read_text(encoding="utf-8").casefold()
