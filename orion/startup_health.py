from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from orion.active_dcs_installation import ActiveDcsInstallation, active_dcs_installation
from orion.dcs_readiness import DcsReadinessReport, inspect_dcs_readiness
from orion.onboarding_config import OnboardingConfig, onboarding_config
from orion.telemetry_handshake import telemetry_handshake
from orion.windows_wasapi_backend import WasapiEndpoint, wasapi_endpoint_catalog


class StartupHealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ACTION_REQUIRED = "action_required"


class RecoveryAction(StrEnum):
    RESELECT_DCS = "reselect_dcs"
    SELECT_SAVED_GAMES = "select_saved_games"
    REPAIR_INTEGRATION = "repair_integration"
    RESELECT_AUDIO = "reselect_audio"
    START_DCS = "start_dcs"


class StartupHealthCheck(BaseModel):
    key: str
    passed: bool
    blocking: bool
    message: str
    recovery_action: RecoveryAction | None = None


class StartupHealthReport(BaseModel):
    state: StartupHealthState
    checks: list[StartupHealthCheck] = Field(default_factory=list)
    active_dcs: ActiveDcsInstallation | None = None
    readiness: DcsReadinessReport | None = None
    audio_endpoint: WasapiEndpoint | None = None
    telemetry_connected: bool = False
    recovery_actions: list[RecoveryAction] = Field(default_factory=list)


def inspect_startup_health() -> StartupHealthReport:
    active = active_dcs_installation.get()
    config = onboarding_config.get()
    live = telemetry_handshake.snapshot()
    checks: list[StartupHealthCheck] = []

    dcs_ok = active is not None and Path(active.executable_path).is_file()
    checks.append(
        StartupHealthCheck(
            key="active_dcs",
            passed=dcs_ok,
            blocking=True,
            message=("Active DCS installation is available" if dcs_ok else "Selected DCS installation is missing or unavailable"),
            recovery_action=None if dcs_ok else RecoveryAction.RESELECT_DCS,
        )
    )

    readiness: DcsReadinessReport | None = None
    if dcs_ok and active is not None:
        readiness = inspect_dcs_readiness(active.saved_games_path)
        saved_ok = readiness.selected_saved_games is not None and Path(readiness.selected_saved_games).is_dir()
        checks.append(
            StartupHealthCheck(
                key="saved_games",
                passed=saved_ok,
                blocking=True,
                message=("DCS Saved Games is available" if saved_ok else "DCS Saved Games is missing or unavailable"),
                recovery_action=None if saved_ok else RecoveryAction.SELECT_SAVED_GAMES,
            )
        )
        checks.append(
            StartupHealthCheck(
                key="export_integration",
                passed=readiness.export_configured,
                blocking=True,
                message=("ORION Export.lua integration is configured" if readiness.export_configured else "ORION Export.lua integration needs repair"),
                recovery_action=None if readiness.export_configured else RecoveryAction.REPAIR_INTEGRATION,
            )
        )

    audio_endpoint = _resolve_audio_endpoint(config)
    audio_ok = _audio_is_available(config, audio_endpoint)
    checks.append(
        StartupHealthCheck(
            key="audio_output",
            passed=audio_ok,
            blocking=False,
            message=("Configured audio output is available" if audio_ok else "Configured audio output is unavailable; reselect or use Windows default"),
            recovery_action=None if audio_ok else RecoveryAction.RESELECT_AUDIO,
        )
    )

    checks.append(
        StartupHealthCheck(
            key="telemetry",
            passed=live.connected,
            blocking=False,
            message=("Live DCS telemetry is connected" if live.connected else "Waiting for live DCS telemetry"),
            recovery_action=None if live.connected else RecoveryAction.START_DCS,
        )
    )

    actions: list[RecoveryAction] = []
    for check in checks:
        if not check.passed and check.recovery_action is not None and check.recovery_action not in actions:
            actions.append(check.recovery_action)

    if any(not item.passed and item.blocking for item in checks):
        state = StartupHealthState.ACTION_REQUIRED
    elif any(not item.passed for item in checks):
        state = StartupHealthState.DEGRADED
    else:
        state = StartupHealthState.HEALTHY

    return StartupHealthReport(
        state=state,
        checks=checks,
        active_dcs=active,
        readiness=readiness,
        audio_endpoint=audio_endpoint,
        telemetry_connected=live.connected,
        recovery_actions=actions,
    )


def _resolve_audio_endpoint(config: OnboardingConfig) -> WasapiEndpoint | None:
    selector = config.audio_output_id
    if selector in {"default", "windows-default"}:
        return None
    return wasapi_endpoint_catalog.choose(selector)


def _audio_is_available(config: OnboardingConfig, endpoint: WasapiEndpoint | None) -> bool:
    if config.audio_output_id in {"default", "windows-default"}:
        return True
    return endpoint is not None and endpoint.active
