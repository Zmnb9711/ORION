from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_LAUNCHER = ROOT / "orion" / "desktop_product_launcher.py"
LEGACY_V2 = ROOT / "orion" / "desktop_app_windows_v2.py"


def _imports(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                found.add((node.module, alias.name))
    return found


def test_product_launcher_uses_canonical_core_process_manager() -> None:
    imports = _imports(PRODUCT_LAUNCHER)

    assert ("orion.core_process", "CoreProcessManager") in imports
    assert ("orion.desktop_app", "CoreServer") not in imports


def test_product_launcher_is_the_only_production_desktop_runner() -> None:
    product_source = PRODUCT_LAUNCHER.read_text(encoding="utf-8")
    legacy_source = LEGACY_V2.read_text(encoding="utf-8")

    assert "def run_desktop_launcher" in product_source
    # The old V2 runner still exists temporarily while its visual shell is being
    # consolidated. This assertion deliberately records the debt instead of
    # pretending V2 is already dead; remove the legacy runner and invert this
    # assertion in the consolidation commit.
    assert "def run_desktop_launcher" in legacy_source


def test_product_runner_keeps_core_alive_when_ui_exits() -> None:
    tree = ast.parse(PRODUCT_LAUNCHER.read_text(encoding="utf-8"), filename=str(PRODUCT_LAUNCHER))
    runner = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_desktop_launcher"
    )
    calls = [node for node in ast.walk(runner) if isinstance(node, ast.Call)]
    method_calls = {
        node.func.attr
        for node in calls
        if isinstance(node.func, ast.Attribute)
    }

    assert "start" in method_calls
    assert "stop" in method_calls
    assert "shutdown" not in method_calls
