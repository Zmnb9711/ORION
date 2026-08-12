from __future__ import annotations

from pathlib import Path

import orion.desktop_app as desktop_app
from orion.desktop_app import CoreServer


def test_source_launcher_uses_core_module_entry_point(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ORION_CORE_EXECUTABLE", raising=False)
    monkeypatch.setattr(desktop_app.sys, "frozen", False, raising=False)
    core = CoreServer("127.0.0.1", 8123, runtime_dir=tmp_path / "runtime")

    command = core._command()

    assert command[0] == desktop_app.sys.executable
    assert command[1:3] == ["-m", "orion.core_main"]
    assert command[-2:] == ["--port", "8123"]


def test_launcher_honors_explicit_core_executable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ORION_CORE_EXECUTABLE", r"C:\Program Files\ORION\ORION-Core.exe")
    core = CoreServer("127.0.0.1", 8000, runtime_dir=tmp_path / "runtime")

    assert core._command() == [
        r"C:\Program Files\ORION\ORION-Core.exe",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]


def test_launcher_attaches_to_existing_core_without_owning_it(monkeypatch, tmp_path: Path) -> None:
    core = CoreServer("127.0.0.1", 8000, runtime_dir=tmp_path / "runtime")
    monkeypatch.setattr(core, "healthy", lambda: True)

    core.start()

    assert core.owns_process is False
    assert core._process is None
