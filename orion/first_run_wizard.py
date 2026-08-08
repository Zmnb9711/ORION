from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from orion.active_dcs_installation import ActiveDcsInstallationStore, active_dcs_installation
from orion.components import component_registry
from orion.dcs_installations import DcsInstallationStore, DcsInstallationType, dcs_installations
from orion.dcs_readiness import inspect_dcs_readiness


class FirstRunState(StrEnum):
    ACTION_REQUIRED = "action_required"
    WAITING_FOR_DCS = "waiting_for_dcs"
    READY_TO_FLY = "ready_to_fly"


class FirstRunCheck(BaseModel):
    key: str
    label: str
    passed: bool
    blocking: bool
    message: str
    action: str | None = None


class FirstRunRequest(BaseModel):
    installation_type: DcsInstallationType = DcsInstallationType.AUTO
    require_active_selection: bool = False
    saved_games_path: str | None = None
    installed_components: list[str] = Field(default_factory=list)
    telemetry_received: bool | None = None
    aircraft_type: str | None = None


class FirstRunReport(BaseModel):
    state: FirstRunState
    headline: str
    checks: list[FirstRunCheck]
    next_action: str | None = None
    installation_type: DcsInstallationType = DcsInstallationType.AUTO
    active_dcs_display_name: str | None = None
    active_dcs_executable: str | None = None
    selected_saved_games: str | None = None


def evaluate_first_run(
    payload: FirstRunRequest,
    installation_store: DcsInstallationStore = dcs_installations,
    active_store: ActiveDcsInstallationStore = active_dcs_installation,
) -> FirstRunReport:
    checks: list[FirstRunCheck] = []
    active = active_store.get()
    active_valid = active is not None and Path(active.executable_path).is_file()
    installations = installation_store.list()
    existing = next((item for item in installations if Path(item.executable_path).is_file()), None)

    if active_valid and active is not None:
        installation_passed = True
        installation_message = f"Active DCS: {active.display_name or active.installation_type.value}"
        installation_action = None
        resolved_type = active.installation_type
    elif payload.require_active_selection:
        installation_passed = False
        if active is not None:
            installation_message = "The selected active DCS executable is no longer available"
            installation_action = "Choose another DCS installation"
        elif existing is not None:
            installation_message = f"DCS found: {existing.name}; select it as active"
            installation_action = "Select this DCS installation as active"
        else:
            installation_message = "No active DCS installation is selected"
            installation_action = "Choose Steam, Standalone, Auto-detect, or Manual path"
        resolved_type = active.installation_type if active is not None else payload.installation_type
    else:
        installation_passed = existing is not None
        installation_message = f"DCS found: {existing.name}" if existing else "No valid DCS executable is registered"
        installation_action = None if existing else "Detect or select DCS.exe"
        resolved_type = active.installation_type if active_valid and active is not None else payload.installation_type

    checks.append(
        FirstRunCheck(
            key="dcs_installation",
            label="DCS World",
            passed=installation_passed,
            blocking=True,
            message=installation_message,
            action=installation_action,
        )
    )

    readiness_path = payload.saved_games_path or (active.saved_games_path if active_valid and active is not None else None)
    readiness = inspect_dcs_readiness(readiness_path)
    saved_games_ok = readiness.selected_saved_games is not None
    checks.append(
        FirstRunCheck(
            key="saved_games",
            label="DCS Saved Games",
            passed=saved_games_ok,
            blocking=True,
            message=(f"Saved Games: {readiness.selected_saved_games}" if saved_games_ok else "DCS Saved Games directory not found"),
            action=None if saved_games_ok else "Select Saved Games\\DCS directory",
        )
    )
    checks.append(
        FirstRunCheck(
            key="export_lua",
            label="Flight Bridge / Export.lua",
            passed=readiness.export_configured,
            blocking=True,
            message="ORION Export.lua hook installed" if readiness.export_configured else "ORION is not connected to DCS Export.lua",
            action=None if readiness.export_configured else "Install ORION DCS integration",
        )
    )

    installed = set(payload.installed_components)
    for component_id, label, blocking in (
        ("orion-core", "ORION Core", True),
        ("dcs-integration", "DCS Integration", True),
        ("aircraft-fa18c", "F/A-18C Aircraft Pack", False),
    ):
        known = component_registry.get(component_id) is not None
        passed = known and component_id in installed
        checks.append(
            FirstRunCheck(
                key=f"component:{component_id}",
                label=label,
                passed=passed,
                blocking=blocking,
                message=f"{label} installed" if passed else f"{label} not installed",
                action=None if passed else f"Install {label}",
            )
        )

    telemetry_ok = payload.telemetry_received is True
    if telemetry_ok and payload.aircraft_type:
        telemetry_message = f"Live telemetry received from {payload.aircraft_type}"
    elif telemetry_ok:
        telemetry_message = "Live DCS telemetry received"
    else:
        telemetry_message = "Waiting for live telemetry from DCS"
    checks.append(
        FirstRunCheck(
            key="telemetry",
            label="Live DCS connection",
            passed=telemetry_ok,
            blocking=False,
            message=telemetry_message,
            action=None if telemetry_ok else "Start DCS and enter an aircraft",
        )
    )

    blocking_failed = [check for check in checks if check.blocking and not check.passed]
    if blocking_failed:
        state = FirstRunState.ACTION_REQUIRED
        headline = "ORION setup requires attention"
        next_action = blocking_failed[0].action
    elif not telemetry_ok:
        state = FirstRunState.WAITING_FOR_DCS
        headline = "Setup complete — waiting for DCS"
        next_action = (
            "Start DCS and enter an aircraft"
            if payload.require_active_selection
            else "Start DCS and enter the F/A-18C"
        )
    else:
        state = FirstRunState.READY_TO_FLY
        headline = "READY TO FLY"
        next_action = None

    return FirstRunReport(
        state=state,
        headline=headline,
        checks=checks,
        next_action=next_action,
        installation_type=resolved_type,
        active_dcs_display_name=active.display_name if active_valid and active is not None else None,
        active_dcs_executable=active.executable_path if active_valid and active is not None else None,
        selected_saved_games=readiness.selected_saved_games,
    )
