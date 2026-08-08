from __future__ import annotations

from contextlib import asynccontextmanager
from importlib import import_module
from importlib.util import find_spec
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Query


LEGACY_CORE_AVAILABLE = find_spec("orion.models") is not None

if LEGACY_CORE_AVAILABLE:
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
    from orion.mission_store import mission_store
    from orion.models import TelemetryEnvelope
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
        transport, _ = await start_udp_bridge(store_telemetry)
        try:
            yield
        finally:
            transport.close()

    app = FastAPI(title="ORION Core", version=__version__, lifespan=lifespan)
else:
    app = FastAPI(title="ORION", version="0.1.0", description="ORION AI Flight Assistant API")


def _include_router_when_available(module_name: str) -> None:
    if find_spec(module_name) is None:
        return
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
    _include_router_when_available(_router_module)


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    if LEGACY_CORE_AVAILABLE:
        return {"status": "ok", "version": __version__}
    return {"status": "ok"}


if LEGACY_CORE_AVAILABLE:
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

    @app.put("/v1/mission-pack/registration", response_model=MissionPackRegistration)
    def register_mission_pack(registration: MissionPackRegistration) -> MissionPackRegistration:
        capability_registry.register(registration)
        _journal.append("mission_pack_registration", registration.model_dump(mode="json"))
        return registration

    @app.get("/v1/mission-pack/registration", response_model=MissionPackRegistration)
    def get_mission_pack_registration() -> MissionPackRegistration:
        registration = capability_registry.get()
        if registration is None:
            raise HTTPException(status_code=404, detail="Mission Pack not detected")
        return registration

    @app.post("/v1/mission-bridge/commands", response_model=MissionCommandResult, status_code=202)
    def send_mission_command(command: MissionCommand) -> MissionCommandResult:
        try:
            result = mission_bridge.send(command)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _journal.append("mission_bridge_command", command.model_dump(mode="json", exclude_none=True))
        return result

    @app.get("/v1/mission-bridge/commands", response_model=list[MissionCommandResult])
    def list_mission_command_results() -> list[MissionCommandResult]:
        return mission_command_statuses.list()

    @app.get("/v1/mission-bridge/commands/{command_id}", response_model=MissionCommandResult)
    def get_mission_command_result(command_id: UUID) -> MissionCommandResult:
        result = mission_command_statuses.get(command_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Mission command not found")
        return result

    @app.put("/v1/mission-bridge/commands/{command_id}/status", response_model=MissionCommandResult)
    def update_mission_command_result(command_id: UUID, result: MissionCommandResult) -> MissionCommandResult:
        if result.command_id != command_id:
            raise HTTPException(status_code=400, detail="Command ID mismatch")
        stored = mission_command_statuses.set(command_id, result.status, result.message)
        _journal.append("mission_bridge_command_status", stored.model_dump(mode="json"))
        return stored

    @app.post("/v1/dialogue", response_model=DialogueResult)
    def process_dialogue(payload: DialogueRequest) -> DialogueResult:
        result = classify_dialogue(payload)
        _journal.append("dialogue", {"request": payload.model_dump(mode="json"), "result": result.model_dump(mode="json")})
        return result

    @app.post("/v1/pending-actions", response_model=PendingAction, status_code=201)
    def create_pending_action(payload: PendingActionCreate) -> PendingAction:
        action = confirmation_store.create(payload)
        _journal.append("pending_action", action.model_dump(mode="json"))
        return action

    @app.get("/v1/pending-actions", response_model=list[PendingAction])
    def list_pending_actions(status: ConfirmationStatus | None = Query(default=None)) -> list[PendingAction]:
        return confirmation_store.list(status=status)

    @app.post("/v1/pending-actions/{action_id}/decision", response_model=PendingAction)
    def decide_pending_action(action_id: str, decision: ConfirmationDecision) -> PendingAction:
        action = confirmation_store.resolve(action_id, decision.confirm)
        if action is None:
            raise HTTPException(status_code=404, detail="Pending action not found or already resolved")
        _journal.append("pending_action_decision", action.model_dump(mode="json"))
        return action

    @app.put("/v1/mission", response_model=MissionSnapshot)
    def replace_mission(snapshot: MissionSnapshot) -> MissionSnapshot:
        mission_store.replace(snapshot)
        _journal.append("mission_snapshot", snapshot.model_dump(mode="json"))
        return snapshot

    @app.get("/v1/mission", response_model=MissionSnapshot)
    def get_mission() -> MissionSnapshot:
        snapshot = mission_store.get()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No mission snapshot received")
        return snapshot

    @app.get("/v1/mission/units", response_model=list[MissionUnit])
    def list_mission_units(coalition: Coalition | None = Query(default=None), alive_only: bool = Query(default=True)) -> list[MissionUnit]:
        return mission_store.units(coalition=coalition, alive_only=alive_only)

    @app.get("/v1/mission/threats", response_model=list[ThreatAssessment])
    def list_threats(latitude: float | None = Query(default=None, ge=-90, le=90), longitude: float | None = Query(default=None, ge=-180, le=180), altitude_m: float | None = Query(default=None), own_coalition: Coalition = Query(default=Coalition.BLUE), horizon_s: float = Query(default=60, ge=0, le=600)) -> list[ThreatAssessment]:
        snapshot = mission_store.get()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No mission snapshot received")
        if latitude is None or longitude is None:
            if _latest is None:
                raise HTTPException(status_code=400, detail="Provide latitude and longitude or ingest own-aircraft telemetry first")
            own_position = MissionPosition(latitude=_latest.state.position.latitude, longitude=_latest.state.position.longitude, altitude_m=_latest.state.position.altitude_m)
        else:
            own_position = MissionPosition(latitude=latitude, longitude=longitude, altitude_m=altitude_m or 0)
        return assess_threats(snapshot=snapshot, own_position=own_position, own_coalition=own_coalition, horizon_s=horizon_s)

    @app.post("/v1/support-requests", response_model=SupportRequest, status_code=201)
    def create_support_request(payload: SupportRequestCreate) -> SupportRequest:
        request = support_requests.create(payload)
        _journal.append("support_request", request.model_dump(mode="json"))
        return request

    @app.get("/v1/support-requests", response_model=list[SupportRequest])
    def list_support_requests() -> list[SupportRequest]:
        return support_requests.list()
