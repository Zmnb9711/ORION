from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
from uuid import uuid4

from orion.mission_bridge_ingest import (
    MissionBridgeSnapshot,
    MissionBridgeTelemetryStore,
)
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.realtime_tools import RealtimeToolCall, RealtimeToolService
from orion.realtime_tools import RealtimeToolResult
from orion.runtime_modules import OrionRuntimeModule, RuntimeModuleRegistry
from orion.telemetry_handshake import TelemetryHandshake


def _telemetry() -> TelemetryEnvelope:
    return TelemetryEnvelope(
        state=AircraftState(
            aircraft_type="FA-18C_hornet",
            callsign="Springfield 1-1",
            position=Position(latitude=41.6, longitude=41.6, altitude_m=20),
            heading_deg=90,
            true_airspeed_mps=0,
        )
    )


class _Atc:
    def __init__(self) -> None:
        self.calls = []

    def get_or_open_session(self, **kwargs):  # noqa: ANN003, ANN202
        self.calls.append(kwargs)
        return SimpleNamespace(session_id=uuid4()), True


class _Gateway:
    def __init__(self) -> None:
        self.calls = []
        self.error: Exception | None = None

    def handle(self, session_id, request):  # noqa: ANN001, ANN202
        self.calls.append((session_id, request))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            domain=request.domain,
            intent="request",
            action="domain_not_yet_wired",
            procedural_state="atc_contact",
            reply="ATC domain is not yet wired.",
            details={},
            requires_parameter=False,
        )


def _service(*, active: bool = True, gateway: _Gateway | None = None):  # noqa: ANN202
    handshake = TelemetryHandshake(stale_after_seconds=60)
    bridge = MissionBridgeTelemetryStore()
    live = _telemetry()
    if active:
        handshake.observe(live)
        bridge.ingest(
            MissionBridgeSnapshot(
                session_id="mission-live-1",
                mission_name="Caucasus Training",
                player_callsign="Springfield 1-1",
                sequence=1,
                generated_at=datetime.now(UTC),
            )
        )
    modules = RuntimeModuleRegistry()
    modules.register(OrionRuntimeModule.VIRTUAL_ATC)
    atc = _Atc()
    gateway = gateway or _Gateway()
    service = RealtimeToolService(
        handshake=handshake,
        mission_bridge=bridge,
        atc=atc,  # type: ignore[arg-type]
        atc_gateway=gateway,
        modules=modules,
        telemetry_getter=lambda: live,
    )
    return service, handshake, bridge, modules, atc, gateway


def _call(text: str, **arguments: object) -> RealtimeToolCall:
    return RealtimeToolCall(
        call_id="atc-1",
        name="orion.virtual_atc.request",
        arguments={"request_text": text, **arguments},
    )


def test_no_mission_atc_request_returns_no_authority_without_fabrication() -> None:
    service, *_ = _service(active=False)
    result = service.execute(_call("Башня, готов к взлёту"))
    assert result.ok is True
    assert result.output["status"] == "unavailable"
    assert result.output["mission_active"] is False
    assert "clearance" not in result.output


def test_active_mission_routes_russian_english_and_free_form_to_core_atc() -> None:
    service, _, _, _, atc, gateway = _service()
    for text, language in (
        ("Ground, запрос запуска", "ru"),
        ("Tower, ready for departure", "en"),
        ("Можно мне вырулить?", "ru"),
    ):
        result = service.execute(_call(text, language=language, domain="ground"))
        assert result.ok is True
        assert result.output["mission_active"] is True
        assert result.output["action"] == "domain_not_yet_wired"
    assert len(atc.calls) == 3
    assert len(gateway.calls) == 3


def test_malformed_arguments_are_rejected_before_atc() -> None:
    service, _, _, _, atc, _ = _service()
    result = service.execute(
        RealtimeToolCall(
            call_id="bad",
            name="orion.virtual_atc.request",
            arguments={"request_text": "Tower", "heading_deg": 999},
        )
    )
    assert result.ok is False
    assert "Invalid Virtual ATC arguments" in (result.error or "")
    assert atc.calls == []


def test_disabled_atc_module_returns_structured_unavailable() -> None:
    service, _, _, modules, atc, _ = _service()
    modules.set_enabled(OrionRuntimeModule.VIRTUAL_ATC, False)
    result = service.execute(_call("Tower, ready"))
    assert result.output["status"] == "unavailable"
    assert result.output["mission_active"] is True
    assert result.output["reason"] == "module_disabled"
    assert atc.calls == []


def test_atc_internal_exception_isolated_from_qwen_transport() -> None:
    gateway = _Gateway()
    gateway.error = RuntimeError("controlled ATC failure")
    service, *_ = _service(gateway=gateway)
    result = service.execute(_call("Tower, ready"))
    assert result.ok is False
    assert result.output["status"] == "internal_error"
    assert result.error == "Virtual ATC failed: RuntimeError"


def test_mission_bridge_disconnect_revokes_tools_without_stopping_qwen_state() -> None:
    service, _, bridge, _, _, _ = _service()
    qwen_state = "streaming"
    assert service.context().mission_active is True
    bridge.disconnect()
    assert service.context().mission_active is False
    assert service.execute(_call("Tower, ready")).output["status"] == "unavailable"
    assert qwen_state == "streaming"


def test_live_qwen_function_call_returns_core_result_and_requests_audio_followup(monkeypatch) -> None:  # noqa: ANN001
    import orion.qwen_live_audio_core as core

    class WebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        def send(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

    class Diagnostics:
        def __init__(self) -> None:
            self.events = []

        def record_websocket_event(self, event: str, **details: object) -> None:
            self.events.append((event, details))

    class Monitor:
        def __init__(self) -> None:
            self.tx = []

        def record_tx(self, timestamp: int) -> None:
            self.tx.append(timestamp)

    calls = []

    def execute(call: RealtimeToolCall) -> RealtimeToolResult:
        calls.append(call)
        return RealtimeToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output={"status": "unavailable", "reason": "no_mission"},
        )

    monkeypatch.setattr(core.realtime_tools, "execute", execute)
    ws = WebSocket()
    diagnostics = Diagnostics()
    monitor = Monitor()
    core.QwenLiveAudioService._handle_realtime_tool_call(
        ws=ws,
        event={
            "type": "response.function_call_arguments.done",
            "call_id": "tool-1",
            "name": "orion_virtual_atc_request",
            "arguments": '{"request_text":"Tower, ready"}',
        },
        diagnostics=diagnostics,  # type: ignore[arg-type]
        monitor=monitor,  # type: ignore[arg-type]
    )
    assert calls[0].name == "orion.virtual_atc.request"
    assert ws.sent[0]["type"] == "conversation.item.create"
    assert ws.sent[1] == {
        "type": "response.create",
        "response": {"modalities": ["text", "audio"]},
    }
    assert monitor.tx
    assert [event for event, _ in diagnostics.events] == [
        "CORE_TOOL_REQUEST",
        "CORE_TOOL_RESULT",
        "CORE_TOOL_FOLLOWUP_REQUESTED",
    ]
