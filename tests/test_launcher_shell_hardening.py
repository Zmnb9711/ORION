from pathlib import Path

import orion.launcher as legacy_launcher
import orion.launcher_main as launcher_main
import orion.launcher_shell as shell
import orion.launcher_ui as launcher_ui


def test_launcher_main_routes_to_canonical_shell() -> None:
    source = Path(launcher_main.__file__).read_text(encoding="utf-8")
    assert "orion.launcher_shell" in source
    assert "field_fixed" not in source
    assert "run_field_fixed_launcher" not in source


def test_canonical_shell_owns_production_lifecycle() -> None:
    source = Path(shell.__file__).read_text(encoding="utf-8")
    assert "CoreProcessManager" in source
    assert "core.start()" in source
    assert "core.detach()" in source
    assert "core.stop()" not in source
    assert hasattr(shell, "OrionLauncher")
    assert hasattr(shell, "run_launcher")


def test_orion_startup_never_opens_browser_automatically() -> None:
    source = Path(legacy_launcher.__file__).read_text(encoding="utf-8")
    assert "webbrowser.open" not in source
    assert "import webbrowser" not in source


def test_ready_stt_ui_hides_install_action_and_matches_spoken_reply() -> None:
    source = Path(launcher_ui.__file__).read_text(encoding="utf-8")
    assert "prepare.pack_forget()" in source
    assert "Всё хорошо. Связь установлена." in source
    assert "Дела отлично. Связь установлена." not in source
