from __future__ import annotations

import os
import sys
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class UninstallComponent(StrEnum):
    LAUNCHER = "launcher"
    CORE = "core"
    WHISPER = "whisper"
    DCS_INTEGRATION = "dcs_integration"


class UninstallRequest(BaseModel):
    """Explicit component-removal request passed from Launcher to helper."""

    components: set[UninstallComponent] = Field(default_factory=set)
    remove_everything: bool = False
    dcs_saved_games_path: str | None = None
    parent_pid: int | None = None

    @model_validator(mode="after")
    def expand_remove_everything(self) -> "UninstallRequest":
        if self.remove_everything:
            self.components = set(UninstallComponent)
        if not self.components:
            raise ValueError("Select at least one ORION component to remove")
        return self

    @property
    def removes_launcher(self) -> bool:
        return UninstallComponent.LAUNCHER in self.components

    @property
    def removes_core(self) -> bool:
        return UninstallComponent.CORE in self.components

    @property
    def removes_whisper(self) -> bool:
        return UninstallComponent.WHISPER in self.components

    @property
    def removes_dcs_integration(self) -> bool:
        return UninstallComponent.DCS_INTEGRATION in self.components

    def summary_lines(self) -> list[str]:
        labels = {
            UninstallComponent.LAUNCHER: "Launcher",
            UninstallComponent.CORE: "Core",
            UninstallComponent.WHISPER: "Whisper runtime + medium model",
            UninstallComponent.DCS_INTEGRATION: "DCS Saved Games integration",
        }
        ordered = (
            UninstallComponent.LAUNCHER,
            UninstallComponent.CORE,
            UninstallComponent.WHISPER,
            UninstallComponent.DCS_INTEGRATION,
        )
        return [labels[item] for item in ordered if item in self.components]


def installation_root() -> Path:
    override = os.environ.get("ORION_INSTALL_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        if executable.parent.name.casefold() in {"launcher", "core", "uninstaller"}:
            return executable.parent.parent
        return executable.parent
    return Path(__file__).resolve().parent.parent


def runtime_root() -> Path:
    configured = os.environ.get("ORION_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        return local / "ORION" / "runtime"
    return Path.home() / ".orion" / "runtime"


def whisper_root() -> Path:
    override = os.environ.get("ORION_WHISPER_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return runtime_root() / "stt" / "whisper.cpp"


def uninstaller_command(request: UninstallRequest) -> list[str]:
    """Return helper command for frozen product or source development."""
    components = ",".join(sorted(item.value for item in request.components))
    arguments = ["--components", components]
    if request.remove_everything:
        arguments.append("--remove-everything")
    if request.dcs_saved_games_path:
        arguments += ["--dcs-saved-games", request.dcs_saved_games_path]
    if request.parent_pid:
        arguments += ["--parent-pid", str(request.parent_pid)]

    if getattr(sys, "frozen", False):
        helper = installation_root() / "Uninstaller" / "ORION-Uninstall.exe"
        if not helper.is_file():
            raise FileNotFoundError(f"ORION uninstall helper is missing: {helper}")
        return [str(helper), *arguments]
    return [sys.executable, "-m", "orion.uninstall_main", *arguments]
