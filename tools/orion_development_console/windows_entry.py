from __future__ import annotations

import argparse
import ctypes
import sys
from collections.abc import Callable, Sequence
from pathlib import Path


APP_TITLE = "ORION Development Console"
VENV_PYTHONW = Path(".venv") / "Scripts" / "pythonw.exe"
REPOSITORY_MARKERS = (
    Path("pyproject.toml"),
    Path("tools") / "orion_development_console" / "__main__.py",
    Path("branding") / "orion.ico",
)


class WindowsEntryError(RuntimeError):
    """A launch prerequisite is absent or points outside the ORION checkout."""


def _is_repository(candidate: Path) -> bool:
    return candidate.is_dir() and (candidate / ".git").exists() and all(
        (candidate / marker).is_file() for marker in REPOSITORY_MARKERS
    )


def resolve_repository(
    requested: Path | None = None,
    *,
    entry_path: Path | None = None,
) -> Path:
    """Resolve only an explicit checkout or the checkout containing this file."""
    if requested is not None:
        candidate = requested.expanduser().resolve()
        if _is_repository(candidate):
            return candidate
        raise WindowsEntryError(
            f"ORION repository is unavailable or incomplete:\n{candidate}"
        )

    current = (entry_path or Path(__file__)).resolve().parent
    for candidate in (current, *current.parents):
        if _is_repository(candidate):
            return candidate
    raise WindowsEntryError("ORION repository could not be resolved from the launcher location.")


def resolve_runtime(repository: Path) -> Path:
    """Return the supported terminal-free interpreter without changing the environment."""
    runtime = repository / VENV_PYTHONW
    if not runtime.is_file():
        raise WindowsEntryError(
            "ORION development Python runtime is unavailable:\n"
            f"{runtime}\n\nThe environment was not created or repaired automatically."
        )
    return runtime.resolve()


def launch_console(
    repository: Path,
    *,
    ui_runner: Callable[[Path], None] | None = None,
) -> None:
    """Launch the existing Console UI and no production lifecycle component."""
    resolve_runtime(repository)
    repository_text = str(repository)
    if repository_text not in sys.path:
        sys.path.insert(0, repository_text)
    if ui_runner is None:
        from tools.orion_development_console.ui import run_ui

        ui_runner = run_ui
    ui_runner(repository)


def show_error(message: str) -> None:
    """Display a native visible error even though the process has no console."""
    ctypes.windll.user32.MessageBoxW(0, message, APP_TITLE, 0x10)


def main(
    argv: Sequence[str] | None = None,
    *,
    error_presenter: Callable[[str], None] = show_error,
    ui_runner: Callable[[Path], None] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=f"Terminal-free {APP_TITLE} entry")
    parser.add_argument("--repository", type=Path)
    args = parser.parse_args(argv)
    try:
        repository = resolve_repository(args.repository)
        launch_console(repository, ui_runner=ui_runner)
    except Exception as error:  # The GUI entry must never fail invisibly.
        error_presenter(f"{APP_TITLE} could not start.\n\n{error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
