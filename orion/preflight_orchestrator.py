from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.dcs_connection_diagnostics import ConnectionState, DcsConnectionReport, diagnose_dcs_connection
from orion.fa18c_live_validation import HornetLiveValidationSnapshot, HornetLiveValidator, hornet_live_validator
from orion.fa18c_mapping_registry import HornetMappingRegistry, hornet_mapping_registry
from orion.fa18c_value_profiles import HornetValueProfileRegistry, hornet_value_profile_registry
from orion.first_run_wizard import FirstRunRequest, FirstRunState, evaluate_first_run
from orion.telemetry_handshake import TelemetryHandshake, telemetry_handshake


class PreflightState(StrEnum):
    ACTION_REQUIRED = "action_required"
    WAITING_FOR_DCS = "waiting_for_dcs"
    UNSUPPORTED_AIRCRAFT = "unsupported_aircraft"
    CALIBRATION_REQUIRED = "calibration_required"
    LIVE_VALIDATION_REQUIRED = "live_validation_required"
    READY_TO_FLY = "ready_to_fly"


class PreflightRequest(BaseModel):
    saved_games_path: str | None = None
    installed_components: list[str] = Field(default_factory=list)


class AircraftBootstrap(BaseModel):
    detected_aircraft: str | None = None
    aircraft_pack: str | None = None
    pack_installed: bool = False
    mapping_present: bool = False
    mapping_complete: bool = False
    mapping_version: str | None = None
    value_profiles_complete: bool = False
    calibration_required: bool = False


class PreflightReport(BaseModel):
    state: PreflightState
    headline: str
    connection: DcsConnectionReport
    aircraft: AircraftBootstrap
    live_validation: HornetLiveValidationSnapshot | None = None
    next_action: str | None = None


_REQUIRED_PROFILE_CONTROLS = {
    "tacan_power",
    "tacan_channel_tens",
    "tacan_channel_ones",
    "tacan_xy",
    "comm1_selector",
    "comm2_selector",
}


def evaluate_preflight(
    payload: PreflightRequest,
    *,
    handshake: TelemetryHandshake = telemetry_handshake,
    mapping_registry: HornetMappingRegistry = hornet_mapping_registry,
    profile_registry: HornetValueProfileRegistry = hornet_value_profile_registry,
    live_validator: HornetLiveValidator = hornet_live_validator,
) -> PreflightReport:
    connection = diagnose_dcs_connection(handshake=handshake)
    snapshot = handshake.snapshot()
    aircraft = snapshot.aircraft_type

    first_run = evaluate_first_run(
        FirstRunRequest(
            saved_games_path=payload.saved_games_path,
            installed_components=payload.installed_components,
        )
    )

    if first_run.state is FirstRunState.ACTION_REQUIRED:
        return PreflightReport(
            state=PreflightState.ACTION_REQUIRED,
            headline="ORION preflight requires attention",
            connection=connection,
            aircraft=AircraftBootstrap(detected_aircraft=aircraft),
            next_action=first_run.next_action,
        )

    if connection.state is not ConnectionState.HEALTHY:
        return PreflightReport(
            state=PreflightState.WAITING_FOR_DCS,
            headline="Waiting for a healthy DCS connection",
            connection=connection,
            aircraft=AircraftBootstrap(detected_aircraft=aircraft),
            next_action=connection.action or "Start DCS and enter an aircraft",
        )

    normalized = (aircraft or "").strip().lower()
    is_hornet = normalized in {"fa-18c", "fa-18c_hornet", "fa-18c lot 20", "fa-18c_hornet lot 20"}
    if not is_hornet:
        return PreflightReport(
            state=PreflightState.UNSUPPORTED_AIRCRAFT,
            headline=f"Aircraft detected: {aircraft or 'unknown'}",
            connection=connection,
            aircraft=AircraftBootstrap(detected_aircraft=aircraft),
            next_action="Select a supported aircraft pack or enter the F/A-18C",
        )

    pack_installed = "aircraft-fa18c" in set(payload.installed_components)
    mapping = mapping_registry.current()
    profiles = profile_registry.current()
    mapping_present = mapping is not None
    mapping_complete = bool(mapping and mapping.validated and mapping.complete())
    value_profiles_complete = bool(
        mapping_complete
        and profiles
        and profiles.mapping_version == mapping.version
        and _REQUIRED_PROFILE_CONTROLS.issubset(profiles.controls)
    )
    calibration_required = not mapping_complete or not value_profiles_complete
    bootstrap = AircraftBootstrap(
        detected_aircraft=aircraft,
        aircraft_pack="aircraft-fa18c",
        pack_installed=pack_installed,
        mapping_present=mapping_present,
        mapping_complete=mapping_complete,
        mapping_version=mapping.version if mapping else None,
        value_profiles_complete=value_profiles_complete,
        calibration_required=calibration_required,
    )

    if not pack_installed:
        return PreflightReport(
            state=PreflightState.ACTION_REQUIRED,
            headline="F/A-18C detected — aircraft pack missing",
            connection=connection,
            aircraft=bootstrap,
            next_action="Install F/A-18C Aircraft Pack",
        )

    if calibration_required:
        return PreflightReport(
            state=PreflightState.CALIBRATION_REQUIRED,
            headline="F/A-18C detected — cockpit calibration required",
            connection=connection,
            aircraft=bootstrap,
            next_action="Start F/A-18C Calibration Wizard",
        )

    validation = live_validator.snapshot()
    if not validation.validated or validation.mapping_version != mapping.version:
        return PreflightReport(
            state=PreflightState.LIVE_VALIDATION_REQUIRED,
            headline="F/A-18C calibrated — validating live cockpit state",
            connection=connection,
            aircraft=bootstrap,
            live_validation=validation,
            next_action="Keep DCS running and hold TACAN/COMM controls on valid detents for live validation",
        )

    return PreflightReport(
        state=PreflightState.READY_TO_FLY,
        headline="READY TO FLY — F/A-18C",
        connection=connection,
        aircraft=bootstrap,
        live_validation=validation,
        next_action=None,
    )
