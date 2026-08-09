from __future__ import annotations

from contextlib import asynccontextmanager
from importlib import import_module
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Query

from orion import __version__
from orion.capabilities import MissionPackRegistration, capability_registry
from orion.commands import CommandDispatcher, DcsCommand
from orion.config import settings
from orion.confirmations import ConfirmationDecision, ConfirmationStatus, PendingAction, PendingActionCreate, confirmation_store
from orion.dialogue import DialogueRequest, DialogueResult, classify_dialogue
from orion.events import EventJournal
from orion.fa18c_live_validation import hornet_live_validator
from orion.fa18c_live_validation_notifications import hornet_live_validation_notifier
from orion.live_telemetry_store import live_telemetry
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit
from orion.mission_bridge import MissionCommand, mission_bridge
from orion.mission_command_status import MissionCommandResult, mission_command_statuses
from orion.mission_control_proactive import proactive_mission_control
from orion.mission_store import mission_store
from orion.models import TelemetryEnvelope
from orion.startup_onboarding import apply_completed_onboarding_at_startup
from orion.support import SupportRequest, SupportRequestCreate, support_requests
from orion.telemetry_handshake import telemetry_handshake
from orion.threats import ThreatAssessment, assess_threats
from orion.udp_bridge import start_udp_bridge


_latest: TelemetryEnvelope | None = None
_journal = EventJournal(settings.event_log_path)
_dispatcher = CommandDispatcher()


def store_telemetry(payload: TelemetryEnvelope) -> None:
    global _latest
    _latest = payload
    live_telemetry.set(payload)
    telemetry_handshake.observe(payload)
    validation = hornet_live_validator.observe(payload)
    hornet_live_validation_notifier.observe(validation)
    _journal.append("telemetry", payload.model_dump(mode="json"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    apply_completed_onboarding_at_startup()
    proactive_mission_control.enable()
    transport, _ = await start_udp_bridge(store_telemetry)
    try:
        yield
    finally:
        proactive_mission_control.disable()
        transport.close()


app = FastAPI(title="ORION Core", version=__version__, lifespan=lifespan)


def _include_router(module_name: str) -> None:
    module = import_module(module_name)
    router = getattr(module, "router", None)
    if not isinstance(router, APIRouter):
        raise RuntimeError(f"{module_name} does not expose a FastAPI APIRouter named 'router'")
    app.include_router(router)


for _router_module in (
    "orion.aircraft_knowledge_api",
    "orion.aar_events_api",
    "orion.coalition_control_api",
    "orion.mission_bridge_api",
    "orion.mission_context_api",
    "orion.mission_control_queries_api",
    "orion.mission_control_jtac_api",
    "orion.mission_control_autonomy_api",
    "orion.cas_9line_api",
    "orion.jtac_api",
    "orion.dialogue_runtime_api",
    "orion.voice_core_api",
    "orion.speech_scheduler_api",
    "orion.tts_audio_api",
    "orion.windows_audio_worker_api",
    "orion.launch_api",
    "orion.dcs_installations_api",
    "orion.dcs_steam_detection_api",
    "orion.dcs_installation_discovery_api",
    "orion.active_dcs_installation_api",
    "orion.dcs_readiness_api",
    "orion.first_run_wizard_api",
    "orion.first_run_actions_api",
    "orion.first_run_session_api",
    "orion.first_run_presentation_api",
    "orion.onboarding_config_api",
    "orion.onboarding_runtime_api",
    "orion.startup_health_api",
    "orion.recovery_orchestrator_api",
    "orion.recovery_launch_api",
    "orion.recovery_presentation_api",
    "orion.application_state_api",
    "orion.tactical_proactive_api",
    "orion.dcs_process_api",
    "orion.flight_console_api",
    "orion.flight_readiness_api",
    "orion.mission_activation_api",
    "orion.mission_catalog_api",
    "orion.mission_preparation_api",
    "orion.orion_settings_api",
    "orion.product_capabilities_api",
    "orion.components_api",
):
    _include_router(_router_module)


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/v1/flight-bridge/telemetry", status_code=202)
@app.post("/v1/telemetry", status_code=202, include_in_schema=False)
def ingest_telemetry(payload: TelemetryEnvelope) -> dict[str, str]:
    store_telemetry(payload)
    return {"status": "accepted", "aircraft_type": payload.state.aircraft_type}


@app.get("/v1/flight-bridge/telemetry/latest", response_model=TelemetryEnvelope)
@app.get("/v1/telemetry/latest", response_model=TelemetryEnvelope, include_in_schema=False)
def latest_telemetry() -> TelemetryEnvelope:
    if _latest is None:
        raise HTTPException(status_code=404, detail="No telemetry received")
    return _latest


@app.post("/v1/flight-bridge/commands", status_code=202)
@app.post("/v1/commands", status_code=202, include_in_schema=False)
def send_command(command: DcsCommand) -> dict[str, str]:
    _dispatcher.send(command)
    _journal.append("flight_bridge_command", command.model_dump(mode="json", exclude_none=True))
    return {"status": "sent", "command": command.command.value}
