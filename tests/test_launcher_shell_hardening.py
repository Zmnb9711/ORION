from pathlib import Path

import orion.launcher_main as launcher_main
import orion.launcher_shell as shell


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
