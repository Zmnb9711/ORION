from __future__ import annotations

import logging
import time
from collections import deque
from threading import RLock
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from orion.airport_atc_dialogue import (
    AtcDialogueDomain,
    AtcDialogueRequest,
    airport_atc_dialogue,
)
from orion.atc_service import VirtualAtcService, virtual_atc
from orion.dialogue import DialogueLanguage
from orion.live_telemetry_store import live_telemetry
from orion.mission_bridge_ingest import MissionBridgeTelemetryStore, mission_bridge_telemetry
from orion.runtime_modules import OrionRuntimeModule, RuntimeModuleRegistry, runtime_modules
from orion.telemetry_handshake import TelemetryHandshake, telemetry_handshake


logger = logging.getLogger(__name__)


class RealtimeToolCall(BaseModel):
    call_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)


class RealtimeToolResult(BaseModel):
    call_id: str
    name: str
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class OrionRealtimeContext(BaseModel):
    mission_active: bool
    reason: str
    mission_id: str | None = None
    mission_name: str | None = None
    aircraft_id: str | None = None
    aircraft_type: str | None = None


class VirtualAtcToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_text: str = Field(min_length=1, max_length=1000)
    domain: AtcDialogueDomain = AtcDialogueDomain.AUTO
    language: DialogueLanguage = DialogueLanguage.AUTO
    altitude_ft: int | None = Field(default=None, ge=-2000, le=100000)
    heading_deg: int | None = Field(default=None, ge=0, le=359)


class AtcDialogueGateway(Protocol):
    def handle(self, session_id: Any, request: AtcDialogueRequest) -> Any: ...


def qwen_live_tool_definition() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "orion_virtual_atc_request",
            "description": (
                "Ask ORION Core's Virtual ATC about the active DCS mission. "
                "Use only for ATC requests, never for ordinary conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "request_text": {
                        "type": "string",
                        "description": "The user's complete ATC request in their language.",
                    },
                    "domain": {
                        "type": "string",
                        "enum": [item.value for item in AtcDialogueDomain],
                    },
                    "language": {
                        "type": "string",
                        "enum": [item.value for item in DialogueLanguage],
                    },
                    "altitude_ft": {"type": "integer"},
                    "heading_deg": {"type": "integer", "minimum": 0, "maximum": 359},
                },
                "required": ["request_text"],
                "additionalProperties": False,
            },
        },
    }


class RealtimeToolService:
    """Core-owned allowlist and context gate for realtime provider tools."""

    def __init__(
        self,
        *,
        handshake: TelemetryHandshake = telemetry_handshake,
        mission_bridge: MissionBridgeTelemetryStore = mission_bridge_telemetry,
        atc: VirtualAtcService = virtual_atc,
        atc_gateway: AtcDialogueGateway = airport_atc_dialogue,
        modules: RuntimeModuleRegistry = runtime_modules,
        telemetry_getter: Callable[[], Any] = live_telemetry.get,
    ) -> None:
        self.handshake = handshake
        self.mission_bridge = mission_bridge
        self.atc = atc
        self.atc_gateway = atc_gateway
        self.modules = modules
        self.telemetry_getter = telemetry_getter
        self._diagnostics: deque[dict[str, object]] = deque(maxlen=500)
        self._diagnostics_lock = RLock()
        self._last_context_state: tuple[bool, str] | None = None

    def diagnostic_snapshot(self) -> list[dict[str, object]]:
        with self._diagnostics_lock:
            return list(self._diagnostics)

    def _record(self, event: str, **details: object) -> None:
        with self._diagnostics_lock:
            self._diagnostics.append(
                {"event": event, "timestamp": time.time(), **details}
            )

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "orion.test.ping",
                "description": "Harmless deterministic ORION Core connectivity smoke tool.",
                "parameters": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "orion.virtual_atc.request",
                "description": "Route one ATC request through current Core mission state and Virtual ATC.",
                "parameters": qwen_live_tool_definition()["function"]["parameters"],
            },
        ]

    def context(self) -> OrionRealtimeContext:
        telemetry = self.handshake.snapshot()
        bridge = self.mission_bridge.state()
        live = self.telemetry_getter()
        if not telemetry.connected or not telemetry.aircraft_type:
            context = OrionRealtimeContext(
                mission_active=False,
                reason="live_aircraft_telemetry_unavailable",
            )
        elif not bridge.connected or bridge.stale or not bridge.session_id:
            context = OrionRealtimeContext(
                mission_active=False,
                reason="mission_bridge_unavailable_or_stale",
                aircraft_type=telemetry.aircraft_type,
            )
        else:
            callsign = bridge.player_callsign
            if not callsign and live is not None:
                callsign = live.state.callsign
            aircraft_id = callsign or telemetry.aircraft_type
            context = OrionRealtimeContext(
                mission_active=True,
                reason="live_telemetry_and_mission_bridge_current",
                mission_id=bridge.session_id,
                mission_name=bridge.mission_name,
                aircraft_id=aircraft_id,
                aircraft_type=telemetry.aircraft_type,
            )
        state = (context.mission_active, context.reason)
        if state != self._last_context_state:
            self._last_context_state = state
            self._record(
                "mission_context_transition",
                mission_active=context.mission_active,
                reason=context.reason,
                atc_available=(
                    context.mission_active
                    and self.modules.status(OrionRuntimeModule.VIRTUAL_ATC).enabled
                ),
            )
        return context

    def execute(self, call: RealtimeToolCall) -> RealtimeToolResult:
        started = time.perf_counter()
        self._record("core_tool_request", call_id=call.call_id, tool_name=call.name)
        result = self._execute(call, started)
        status = result.output.get("status") if isinstance(result.output, dict) else None
        self._record(
            "core_tool_result",
            call_id=call.call_id,
            tool_name=call.name,
            accepted=result.ok,
            status=status,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return result

    def _execute(self, call: RealtimeToolCall, started: float) -> RealtimeToolResult:
        if call.name == "orion.test.ping":
            message = call.arguments.get("message")
            return RealtimeToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=True,
                output={
                    "status": "ok",
                    "tool": "orion.test.ping",
                    "message": "pong" if message is None else str(message),
                },
            )
        if call.name != "orion.virtual_atc.request":
            return RealtimeToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                error="Tool is not enabled for ORION realtime voice.",
            )
        return self._execute_atc(call, started)

    def _execute_atc(self, call: RealtimeToolCall, started: float) -> RealtimeToolResult:
        try:
            arguments = VirtualAtcToolArguments.model_validate(call.arguments)
        except ValidationError as exc:
            return RealtimeToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                error=f"Invalid Virtual ATC arguments: {exc}",
            )
        context = self.context()
        if not context.mission_active:
            return self._unavailable(call, context.reason, started, context=context)
        module = self.modules.status(OrionRuntimeModule.VIRTUAL_ATC)
        if not module.available or not module.enabled:
            return self._unavailable(call, module.reason, started, context=context)
        if context.mission_id is None or context.aircraft_id is None:
            return self._unavailable(call, "active_mission_identity_incomplete", started, context=context)
        try:
            status, created = self.atc.get_or_open_session(
                mission_id=context.mission_id,
                aircraft_id=context.aircraft_id,
                procedural_state="atc_contact",
            )
            result = self.atc_gateway.handle(
                status.session_id,
                AtcDialogueRequest(
                    text=arguments.request_text,
                    domain=arguments.domain,
                    language=arguments.language,
                    altitude_ft=arguments.altitude_ft,
                    heading_deg=arguments.heading_deg,
                ),
            )
        except (KeyError, ValueError) as exc:
            return RealtimeToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                output={
                    "status": "unavailable",
                    "reason": str(exc),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                },
                error=str(exc),
            )
        except Exception as exc:
            # Deliberate provider/Core boundary isolation: an ATC subsystem bug
            # must become a structured tool error, not terminate Qwen transport.
            logger.exception("Virtual ATC realtime tool failed")
            return RealtimeToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                output={
                    "status": "internal_error",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                },
                error=f"Virtual ATC failed: {type(exc).__name__}",
            )
        return RealtimeToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output={
                "status": "ok",
                "mission_active": True,
                "mission_id": context.mission_id,
                "aircraft_type": context.aircraft_type,
                "atc_session_id": str(status.session_id),
                "session_created": created,
                "domain": result.domain.value,
                "intent": result.intent,
                "action": result.action,
                "procedural_state": result.procedural_state,
                "reply": result.reply,
                "details": result.details,
                "requires_parameter": result.requires_parameter,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        )

    @staticmethod
    def _unavailable(
        call: RealtimeToolCall,
        reason: str,
        started: float,
        *,
        context: OrionRealtimeContext,
    ) -> RealtimeToolResult:
        return RealtimeToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output={
                "status": "unavailable",
                "mission_active": context.mission_active,
                "reason": reason,
                "aircraft_type": context.aircraft_type,
                "message": "No active DCS mission/ATC context is available.",
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        )


realtime_tools = RealtimeToolService()
