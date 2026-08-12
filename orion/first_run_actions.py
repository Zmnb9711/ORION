from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from enum import StrEnum

from pydantic import BaseModel, Field

from orion.active_dcs_installation import ActiveDcsInstallation, active_dcs_installation
from orion.dcs_installation_discovery import DcsDiscoveryCandidate, DcsDiscoveryResult, discover_dcs_installations
from orion.dcs_installations import DcsInstallationType
from orion.dcs_readiness import DcsReadinessReport, inspect_dcs_readiness, install_export_integration
from orion.telemetry_handshake import telemetry_handshake


class FirstRunAction(StrEnum):
    DETECT = "detect"
    SELECT_ACTIVE = "select_active"
    INSTALL_INTEGRATION = "install_integration"
    TEST_CONNECTION = "test_connection"


class SelectActiveRequest(BaseModel):
    installation_type: DcsInstallationType
    executable_path: str
    install_root: str | None = None
    saved_games_path: str | None = None
    display_name: str | None = None


class FirstRunActionResult(BaseModel):
    action: FirstRunAction
    ok: bool
    message: str
    discovery: DcsDiscoveryResult | None = None
    active: ActiveDcsInstallation | None = None
    readiness: DcsReadinessReport | None = None
    telemetry_connected: bool | None = None
    aircraft_type: str | None = None
    next_actions: list[FirstRunAction] = Field(default_factory=list)

    @property
    def candidates(self) -> list[DcsDiscoveryCandidate]:
        """Stable UI-facing view of usable detected installations.

        Raw discovery may intentionally retain stale/incomplete paths for
        diagnostics, but the desktop selector must never choose a candidate
        whose DCS executable does not exist. This keeps an obsolete C: folder
        from shadowing a valid D:\\SteamLibrary installation.
        """
        if self.discovery is None:
            return []
        return [item for item in self.discovery.candidates if item.exists]


def detect_installations(mode: DcsInstallationType = DcsInstallationType.AUTO) -> FirstRunActionResult:
    discovery = discover_dcs_installations(mode=mode)
    valid = [item for item in discovery.candidates if item.exists]
    return FirstRunActionResult(
        action=FirstRunAction.DETECT,
        ok=bool(valid),
        message=(f"Found {len(valid)} DCS installation(s)" if valid else "No DCS installations found"),
        discovery=discovery,
        next_actions=[FirstRunAction.SELECT_ACTIVE] if valid else [FirstRunAction.DETECT],
    )


def select_active_installation(payload: SelectActiveRequest) -> FirstRunActionResult:
    selection = active_dcs_installation.set(ActiveDcsInstallation(**payload.model_dump()))
    readiness = inspect_dcs_readiness(selection.saved_games_path)
    next_actions = []
    if not readiness.export_configured:
        next_actions.append(FirstRunAction.INSTALL_INTEGRATION)
    next_actions.append(FirstRunAction.TEST_CONNECTION)
    return FirstRunActionResult(
        action=FirstRunAction.SELECT_ACTIVE,
        ok=True,
        message=f"Active DCS selected: {selection.display_name or selection.installation_type.value}",
        active=selection,
        readiness=readiness,
        next_actions=next_actions,
    )


def install_active_integration(saved_games_path: str | None = None) -> FirstRunActionResult:
    active = active_dcs_installation.get()
    selected = saved_games_path or (active.saved_games_path if active else None)
    if selected is None:
        return FirstRunActionResult(
            action=FirstRunAction.INSTALL_INTEGRATION,
            ok=False,
            message="Select DCS Saved Games before installing integration",
            next_actions=[FirstRunAction.SELECT_ACTIVE],
        )
    readiness = install_export_integration(selected)
    return FirstRunActionResult(
        action=FirstRunAction.INSTALL_INTEGRATION,
        ok=readiness.export_configured,
        message=("ORION DCS integration installed" if readiness.export_configured else "ORION DCS integration is not ready"),
        active=active,
        readiness=readiness,
        next_actions=[FirstRunAction.TEST_CONNECTION],
    )


def test_live_connection() -> FirstRunActionResult:
    # Launcher and Core are intentionally separate processes. The live telemetry
    # handshake is in-memory Core state, so a Launcher-side test must ask Core
    # rather than inspect the Launcher's own empty telemetry_handshake instance.
    if os.environ.get("ORION_PROCESS_ROLE") == "launcher":
        return _test_live_connection_via_core()
    return _test_live_connection_local()


def _test_live_connection_local() -> FirstRunActionResult:
    live = telemetry_handshake.snapshot()
    return FirstRunActionResult(
        action=FirstRunAction.TEST_CONNECTION,
        ok=live.connected,
        message=("Live DCS telemetry received" if live.connected else "Waiting for live telemetry from DCS"),
        active=active_dcs_installation.get(),
        telemetry_connected=live.connected,
        aircraft_type=live.aircraft_type,
        next_actions=[] if live.connected else [FirstRunAction.TEST_CONNECTION],
    )


def _test_live_connection_via_core() -> FirstRunActionResult:
    base_url = os.environ.get("ORION_CORE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/v1/first-run/actions/test-connection",
        data=b"",
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return FirstRunActionResult(
            action=FirstRunAction.TEST_CONNECTION,
            ok=False,
            message=f"Unable to query ORION Core telemetry status: {exc}",
            telemetry_connected=False,
            next_actions=[FirstRunAction.TEST_CONNECTION],
        )
    return FirstRunActionResult.model_validate(payload)
