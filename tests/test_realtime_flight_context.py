from __future__ import annotations

import asyncio
import threading
from typing import Any, cast
from orion.flight_context import FlightContextService, FlightContextUpdateGate
from orion.live_telemetry_store import LiveTelemetryStore
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.qwen_live_audio_core import QWEN_INSTRUCTIONS, _audio_session_update
from orion.srs_protocol import (
    SrsRadioState,
    build_radio_update_message,
    build_sync_message,
)
from orion.yandex_realtime_provider import YANDEX_INSTRUCTIONS
from orion.yandex_realtime_session import YandexRealtimeSession


class _Endpoint:
    transport_id = "direct"


class _SrsEndpoint(_Endpoint):
    transport_id = "srs"


class _Diagnostics:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def record(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


class _WebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


def _context() -> FlightContextService:
    store = LiveTelemetryStore()
    store.set(
        TelemetryEnvelope(
            protocol_version="0.3",
            source="dcs-export",
            sequence=42,
            state=AircraftState(
                aircraft_type="FA-18C_hornet",
                position=Position(
                    latitude=41.61,
                    longitude=41.60,
                    altitude_m=38,
                    altitude_agl_m=1,
                ),
                heading_deg=251,
                true_airspeed_mps=1,
                vertical_speed_mps=0,
            ),
        )
    )
    return FlightContextService(store)


def _yandex_payload(endpoint: object) -> tuple[dict[str, object], _Diagnostics]:
    diagnostics = _Diagnostics()
    gate = FlightContextUpdateGate(YANDEX_INSTRUCTIONS, context=_context())
    session = YandexRealtimeSession(
        "api-memory-only",
        "folder",
        endpoint,  # type: ignore[arg-type]
        threading.Event(),
        diagnostics,
        flight_context_gate=gate,
    )
    websocket = _WebSocket()
    assert asyncio.run(session._send_flight_context_update(websocket, force=True))
    return websocket.sent[0], diagnostics


def test_yandex_direct_and_srs_receive_equivalent_semantic_flight_context() -> None:
    direct, direct_diagnostics = _yandex_payload(_Endpoint())
    srs, srs_diagnostics = _yandex_payload(_SrsEndpoint())
    assert direct == srs
    session = cast(dict[str, Any], direct["session"])
    instructions = str(session["instructions"])
    assert "F/A-18C Hornet" in instructions
    assert "FA-18C_hornet" in instructions
    for diagnostics in (direct_diagnostics, srs_diagnostics):
        event, fields = diagnostics.events[-1]
        assert event == "flight_context_applied"
        assert fields["context_fresh"] is True
        assert fields["aircraft_type"] == "FA-18C_hornet"
        assert "api-memory-only" not in repr(fields)


def test_qwen_direct_session_keeps_audio_tools_and_receives_same_flight_facts() -> None:
    update = _context().ai_update(QWEN_INSTRUCTIONS)
    payload = _audio_session_update(
        "qwen3.5-omni-flash-realtime",
        "Tina",
        instructions=update.instructions,
    )
    session = cast(dict[str, Any], payload["session"])
    assert "F/A-18C Hornet" in session["instructions"]
    assert session["input_audio_format"] == "pcm"
    assert session["output_audio_format"] == "pcm"
    assert session["tools"]


def test_flight_context_has_no_effect_on_srs_radioinfo_or_readiness_payloads() -> None:
    state = SrsRadioState(frequency_hz=251_000_000.0, modulation=0)
    guid = "AbCdEfGhIjKlMnOpQrStUv"
    sync = build_sync_message(guid, "ORION", radio_state=state)
    update = build_radio_update_message(
        guid,
        "ORION",
        2,
        state.frequency_hz,
        radio_state=state,
    )
    sync_client = cast(dict[str, object], sync["Client"])
    update_client = cast(dict[str, object], update["Client"])
    assert sync_client["RadioInfo"] == update_client["RadioInfo"]
    assert "FlightContext" not in repr(sync)
    assert "flight_context" not in repr(update)
