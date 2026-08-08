from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.active_dcs_installation import ActiveDcsInstallation, active_dcs_installation
from orion.dcs_installation_discovery import DcsDiscoveryCandidate, discover_dcs_installations
from orion.dcs_installations import DcsInstallationType
from orion.dcs_readiness import DcsReadinessReport, inspect_dcs_readiness
from orion.first_run_actions import FirstRunAction
from orion.telemetry_handshake import telemetry_handshake


class FirstRunSessionStep(StrEnum):
    DETECT = "detect"
    SELECT_ACTIVE = "select_active"
    INSTALL_INTEGRATION = "install_integration"
    TEST_CONNECTION = "test_connection"
    READY = "ready"


class FirstRunSessionState(BaseModel):
    step: FirstRunSessionStep
    progress_percent: int = Field(ge=0, le=100)
    installation_type: DcsInstallationType
    candidates: list[DcsDiscoveryCandidate] = Field(default_factory=list)
    active: ActiveDcsInstallation | None = None
    readiness: DcsReadinessReport | None = None
    telemetry_connected: bool = False
    aircraft_type: str | None = None
    next_action: FirstRunAction | None = None
    message: str


def get_first_run_session(
    mode: DcsInstallationType = DcsInstallationType.AUTO,
) -> FirstRunSessionState:
    active = active_dcs_installation.get()
    discovery = discover_dcs_installations(mode=mode)
    candidates = [item for item in discovery.candidates if item.exists]
    live = telemetry_handshake.snapshot()

    if active is None:
        if candidates:
            return FirstRunSessionState(
                step=FirstRunSessionStep.SELECT_ACTIVE,
                progress_percent=25,
                installation_type=mode,
                candidates=candidates,
                telemetry_connected=live.connected,
                aircraft_type=live.aircraft_type,
                next_action=FirstRunAction.SELECT_ACTIVE,
                message="Select which DCS installation ORION should use",
            )
        return FirstRunSessionState(
            step=FirstRunSessionStep.DETECT,
            progress_percent=0,
            installation_type=mode,
            candidates=[],
            telemetry_connected=live.connected,
            aircraft_type=live.aircraft_type,
            next_action=FirstRunAction.DETECT,
            message="Detect or provide a DCS installation",
        )

    readiness = inspect_dcs_readiness(active.saved_games_path)
    if not readiness.export_configured:
        return FirstRunSessionState(
            step=FirstRunSessionStep.INSTALL_INTEGRATION,
            progress_percent=50,
            installation_type=active.installation_type,
            candidates=candidates,
            active=active,
            readiness=readiness,
            telemetry_connected=live.connected,
            aircraft_type=live.aircraft_type,
            next_action=FirstRunAction.INSTALL_INTEGRATION,
            message="Install or repair the ORION DCS integration",
        )

    if not live.connected:
        return FirstRunSessionState(
            step=FirstRunSessionStep.TEST_CONNECTION,
            progress_percent=75,
            installation_type=active.installation_type,
            candidates=candidates,
            active=active,
            readiness=readiness,
            telemetry_connected=False,
            next_action=FirstRunAction.TEST_CONNECTION,
            message="Start DCS, enter an aircraft, and test the live connection",
        )

    return FirstRunSessionState(
        step=FirstRunSessionStep.READY,
        progress_percent=100,
        installation_type=active.installation_type,
        candidates=candidates,
        active=active,
        readiness=readiness,
        telemetry_connected=True,
        aircraft_type=live.aircraft_type,
        next_action=None,
        message="ORION is ready to fly",
    )
