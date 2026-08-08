from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from orion.active_dcs_installation import ActiveDcsInstallation, active_dcs_installation
from orion.dcs_installation_discovery import discover_dcs_installations
from orion.dcs_readiness import install_export_integration
from orion.onboarding_config import OnboardingConfig, onboarding_config
from orion.startup_health import RecoveryAction, StartupHealthReport, inspect_startup_health
from orion.windows_audio_worker import AudioDevice, windows_audio_worker
from orion.windows_wasapi_backend import wasapi_endpoint_catalog


class RecoveryResult(BaseModel):
    action: RecoveryAction
    ok: bool
    message: str
    health: StartupHealthReport
    active_dcs: ActiveDcsInstallation | None = None
    config: OnboardingConfig | None = None


def run_recovery(action: RecoveryAction) -> RecoveryResult:
    if action is RecoveryAction.REPAIR_INTEGRATION:
        return _repair_integration()
    if action is RecoveryAction.RESELECT_DCS:
        return _rediscover_dcs()
    if action is RecoveryAction.RESELECT_AUDIO:
        return _fallback_audio()
    if action is RecoveryAction.SELECT_SAVED_GAMES:
        return RecoveryResult(
            action=action,
            ok=False,
            message="Saved Games selection requires an explicit user choice",
            health=inspect_startup_health(),
            active_dcs=active_dcs_installation.get(),
            config=onboarding_config.get(),
        )
    if action is RecoveryAction.START_DCS:
        return RecoveryResult(
            action=action,
            ok=False,
            message="Start DCS using the active launch profile, then retry the health check",
            health=inspect_startup_health(),
            active_dcs=active_dcs_installation.get(),
            config=onboarding_config.get(),
        )
    raise ValueError(f"Unsupported recovery action: {action}")


def _repair_integration() -> RecoveryResult:
    active = active_dcs_installation.get()
    if active is None or not active.saved_games_path:
        return RecoveryResult(
            action=RecoveryAction.REPAIR_INTEGRATION,
            ok=False,
            message="Cannot repair integration until DCS Saved Games is selected",
            health=inspect_startup_health(),
            active_dcs=active,
            config=onboarding_config.get(),
        )
    report = install_export_integration(active.saved_games_path)
    health = inspect_startup_health()
    return RecoveryResult(
        action=RecoveryAction.REPAIR_INTEGRATION,
        ok=report.export_configured,
        message=("ORION DCS integration repaired" if report.export_configured else "ORION DCS integration repair did not complete"),
        health=health,
        active_dcs=active,
        config=onboarding_config.get(),
    )


def _rediscover_dcs() -> RecoveryResult:
    config = onboarding_config.get()
    discovery = discover_dcs_installations(mode=config.preferred_dcs_type)
    candidates = [item for item in discovery.candidates if item.exists]
    if len(candidates) != 1:
        return RecoveryResult(
            action=RecoveryAction.RESELECT_DCS,
            ok=False,
            message=("No replacement DCS installation found" if not candidates else "Multiple DCS installations found; user selection is required"),
            health=inspect_startup_health(),
            active_dcs=active_dcs_installation.get(),
            config=config,
        )
    candidate = candidates[0]
    saved = next((item.path for item in candidate.saved_games if item.exists), None)
    selection = ActiveDcsInstallation(
        installation_type=candidate.installation_type,
        executable_path=candidate.executable_path,
        install_root=candidate.install_root,
        saved_games_path=saved,
        display_name=candidate.display_name,
    )
    active_dcs_installation.set(selection)
    return RecoveryResult(
        action=RecoveryAction.RESELECT_DCS,
        ok=True,
        message=f"Active DCS recovered: {selection.display_name or selection.installation_type.value}",
        health=inspect_startup_health(),
        active_dcs=selection,
        config=config,
    )


def _fallback_audio() -> RecoveryResult:
    config = onboarding_config.get()
    vr = wasapi_endpoint_catalog.vr_candidates() if config.prefer_vr_audio else []
    endpoint = vr[0] if vr else wasapi_endpoint_catalog.choose("default")
    if endpoint is None:
        device_id = "windows-default"
        name = "Windows default audio output"
    else:
        device_id = endpoint.device_id
        name = endpoint.name
    updated = config.model_copy(update={"audio_output_id": device_id})
    onboarding_config.set(updated)
    windows_audio_worker.select_device(
        AudioDevice(device_id=device_id, name=name, is_default=device_id in {"default", "windows-default"})
    )
    return RecoveryResult(
        action=RecoveryAction.RESELECT_AUDIO,
        ok=True,
        message=f"Audio output recovered: {name}",
        health=inspect_startup_health(),
        active_dcs=active_dcs_installation.get(),
        config=updated,
    )
