"""Provider-only Yandex Realtime PCM session.

This module owns the Yandex WebSocket and provider event lifecycle. It has no
PortAudio, SRS, codec, device, EAM, DCS, or tool dependency.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from orion.flight_context import FlightContextUpdateGate
from orion.realtime_audio_transport import RealtimePcmEndpoint
from orion.realtime_interaction_state import RealtimeInteractionState
from orion.realtime_test_evidence import realtime_test_evidence
from orion.yandex_realtime_provider import (
    build_yandex_url,
    decode_yandex_output_audio,
    encode_yandex_input_audio,
    sanitize_yandex_error,
    YANDEX_INSTRUCTIONS,
    yandex_authorization_headers,
    yandex_session_update,
)


class SessionDiagnostics(Protocol):
    def record(self, event: str, **fields: object) -> None: ...


@dataclass(frozen=True, slots=True)
class YandexSessionResult:
    close_code: int | None
    clean_close: bool
    local_close_owner: bool


class YandexRealtimeSession:
    """One bounded provider session over an injected provider-native PCM endpoint."""

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        endpoint: RealtimePcmEndpoint,
        stop_event: threading.Event,
        diagnostics: SessionDiagnostics,
        *,
        on_streaming: Callable[[], None] | None = None,
        flight_context_gate: FlightContextUpdateGate | None = None,
        interaction_state: RealtimeInteractionState | None = None,
    ) -> None:
        self._api_key = api_key
        self._folder_id = folder_id
        self._endpoint = endpoint
        self._stop = stop_event
        self._diagnostics = diagnostics
        self._on_streaming = on_streaming or (lambda: None)
        self._flight_context = flight_context_gate or FlightContextUpdateGate(
            YANDEX_INSTRUCTIONS
        )
        self._interaction = interaction_state or RealtimeInteractionState()

    async def _send_flight_context_update(
        self,
        websocket: Any,
        *,
        force: bool = False,
    ) -> bool:
        deferred_before = self._flight_context.deferred_count
        coalesced_before = self._flight_context.coalesced_count
        update = self._flight_context.next_update(
            force=force,
            safe_to_apply=force or self._interaction.safe_to_refresh,
        )
        if self._flight_context.deferred_count != deferred_before:
            self._diagnostics.record(
                "flight_context_deferred",
                context_deferred_count=self._flight_context.deferred_count,
                active_turn_id=self._interaction.current_turn_id(),
                provider="yandex",
            )
        if self._flight_context.coalesced_count != coalesced_before:
            self._diagnostics.record(
                "flight_context_coalesced",
                context_coalesced_count=self._flight_context.coalesced_count,
                active_turn_id=self._interaction.current_turn_id(),
                provider="yandex",
            )
        if update is None:
            return False
        await websocket.send_json(yandex_session_update(instructions=update.instructions))
        count = self._flight_context.mark_applied(update)
        fields = {
            "context_state": update.state.value,
            "context_fresh": update.fresh,
            "aircraft_type": update.aircraft_type,
            "context_generation": update.generation,
            "context_version": update.context_version,
            "context_update_count": count,
            "context_deferred_count": self._flight_context.deferred_count,
            "context_coalesced_count": self._flight_context.coalesced_count,
            "provider": "yandex",
        }
        self._diagnostics.record("flight_context_update_sent", **fields)
        self._diagnostics.record("flight_context_applied", **fields)
        return True

    async def run(self) -> YandexSessionResult:
        import aiohttp

        websocket: Any = None
        send_task: asyncio.Task[None] | None = None
        receive_task: asyncio.Task[None] | None = None
        close_owned = False

        async def send_worker() -> None:
            while not self._stop.is_set():
                await self._send_flight_context_update(websocket)
                pcm = await asyncio.to_thread(self._endpoint.read_input, 0.1)
                if pcm is None:
                    continue
                if len(pcm) % 2:
                    raise ValueError("Provider input PCM is not aligned to int16 samples")
                await websocket.send_json(encode_yandex_input_audio(pcm))

        async def receive_worker() -> None:
            latest_response_id: str | None = None
            while not self._stop.is_set():
                message = await websocket.receive()
                if message.type is aiohttp.WSMsgType.TEXT:
                    event = message.json()
                    kind = str(event.get("type") or "")
                    if kind == "input_audio_buffer.speech_started":
                        turn_id = self._interaction.speech_started()
                        self._endpoint.input_speech_started()
                        self._diagnostics.record("speech_started", turn_id=turn_id)
                    elif kind == "input_audio_buffer.speech_stopped":
                        turn_id = self._interaction.speech_stopped()
                        self._diagnostics.record("speech_stopped", turn_id=turn_id)
                    elif kind == "conversation.item.input_audio_transcription.completed":
                        transcript = str(event.get("transcript") or "")
                        realtime_test_evidence.record_transcript(
                            "user",
                            transcript,
                            turn_id=self._interaction.current_turn_id(),
                            event_id=str(event.get("event_id") or ""),
                            provider_item_id=str(event.get("item_id") or ""),
                        )
                        self._diagnostics.record(
                            "transcription_completed",
                            turn_id=self._interaction.current_turn_id(),
                            provider_item_id=str(event.get("item_id") or ""),
                            characters=len(transcript),
                            persisted=False,
                        )
                    elif kind == "conversation.item.input_audio_transcription.failed":
                        self._diagnostics.record(
                            "transcription_failed",
                            error=sanitize_yandex_error(event.get("error") or "failed", self._api_key),
                        )
                    elif kind == "response.created":
                        response = event.get("response") or {}
                        response_id = str(
                            response.get("id") or event.get("response_id") or "unknown"
                        )
                        latest_response_id = response_id
                        turn_id = self._interaction.response_started(response_id)
                        self._endpoint.response_started(response_id)
                        self._diagnostics.record(
                            "response_created",
                            response_id=response_id,
                            turn_id=turn_id,
                        )
                    elif kind == "response.output_audio.delta":
                        pcm = decode_yandex_output_audio(event)
                        response_id = str(
                            event.get("response_id") or latest_response_id or "unknown"
                        )
                        first_audio = self._interaction.first_audio(response_id)
                        if first_audio is not None:
                            summary = self._interaction.latency_summary()
                            self._diagnostics.record(
                                "response_first_audio",
                                response_id=response_id,
                                turn_id=first_audio.turn_id,
                                response_created_to_first_audio_ms=(
                                    first_audio.response_created_to_first_audio_ms
                                ),
                                speech_stopped_to_first_audio_ms=(
                                    first_audio.speech_stopped_to_first_audio_ms
                                ),
                                latency_sample_count=summary.sample_count,
                                latency_latest_ms=summary.latest_ms,
                                latency_median_ms=summary.median_ms,
                                latency_p90_ms=summary.p90_ms,
                                latency_maximum_ms=summary.maximum_ms,
                            )
                        self._endpoint.response_audio(response_id, pcm)
                        self._diagnostics.record(
                            "audio_delta",
                            response_id=response_id,
                            byte_count=len(pcm),
                        )
                    elif kind == "response.output_audio.done":
                        response_id = str(
                            event.get("response_id") or latest_response_id or "unknown"
                        )
                        self._endpoint.response_audio_done(response_id)
                        self._diagnostics.record("audio_done", response_id=response_id)
                    elif kind in {
                        "response.output_audio_transcript.done",
                        "response.output_text.done",
                    }:
                        response_id = str(
                            event.get("response_id") or latest_response_id or "unknown"
                        )
                        realtime_test_evidence.record_transcript(
                            "assistant",
                            str(event.get("transcript") or event.get("text") or ""),
                            turn_id=self._interaction.turn_for_response(response_id),
                            response_id=response_id,
                            event_id=str(event.get("event_id") or ""),
                            provider_item_id=str(event.get("item_id") or ""),
                        )
                    elif kind == "response.done":
                        response = event.get("response") or {}
                        response_id = str(
                            response.get("id")
                            or event.get("response_id")
                            or latest_response_id
                            or "unknown"
                        )
                        status = str(response.get("status") or "")
                        self._endpoint.response_done(response_id, status)
                        turn_id = self._interaction.response_done(response_id)
                        self._diagnostics.record(
                            "response_done",
                            response_id=response_id,
                            turn_id=turn_id,
                            status=status,
                        )
                    elif kind == "error":
                        raise RuntimeError(event.get("error") or "Yandex provider error")
                    else:
                        self._diagnostics.record(
                            kind or "provider_event",
                            provider_event_id=str(event.get("event_id") or ""),
                        )
                elif message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                }:
                    if not self._stop.is_set():
                        raise ConnectionError(
                            f"Yandex WebSocket closed unexpectedly: {websocket.close_code}"
                        )
                    return
                elif message.type is aiohttp.WSMsgType.ERROR:
                    raise ConnectionError(websocket.exception() or "Yandex WebSocket error")

        timeout = aiohttp.ClientTimeout(total=None, connect=4.0)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            websocket = await client.ws_connect(
                build_yandex_url(self._folder_id),
                headers=yandex_authorization_headers(self._api_key),
                heartbeat=20.0,
                autoclose=True,
            )
            self._diagnostics.record("websocket_connected")
            try:
                await self._send_flight_context_update(websocket, force=True)
                deadline = time.monotonic() + 15.0
                while not self._stop.is_set():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Timed out waiting for Yandex session.updated")
                    try:
                        message = await asyncio.wait_for(websocket.receive(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                    if message.type is aiohttp.WSMsgType.TEXT:
                        event = message.json()
                        kind = str(event.get("type") or "")
                        self._diagnostics.record(kind or "handshake_event")
                        if kind == "session.updated":
                            break
                        if kind == "error":
                            raise RuntimeError(event.get("error") or "Yandex provider error")
                    else:
                        raise ConnectionError("Yandex closed before session.updated")
                if not self._stop.is_set():
                    self._endpoint.start()
                    self._on_streaming()
                    send_task = asyncio.create_task(send_worker(), name="orion-yandex-send")
                    receive_task = asyncio.create_task(
                        receive_worker(), name="orion-yandex-receive"
                    )
                    while True:
                        failure = self._endpoint.failure()
                        if failure is not None:
                            raise failure
                        if self._stop.is_set():
                            break
                        await asyncio.sleep(0.05)
                        for task in (send_task, receive_task):
                            if task.done():
                                error = task.exception()
                                if error is not None:
                                    raise error
                                if not self._stop.is_set():
                                    raise ConnectionError(
                                        f"{task.get_name()} stopped unexpectedly"
                                    )
            finally:
                self._stop.set()
                self._endpoint.stop()
                if send_task is not None and not send_task.done():
                    send_task.cancel()
                    try:
                        await send_task
                    except (asyncio.CancelledError, Exception):
                        pass
                if not websocket.closed:
                    close_owned = True
                    await websocket.close(code=1000)
                if receive_task is not None and not receive_task.done():
                    receive_task.cancel()
                    try:
                        await receive_task
                    except (asyncio.CancelledError, Exception):
                        pass
                code = websocket.close_code
                clean = code == 1000
                self._diagnostics.record(
                    "websocket_closed",
                    close_code=code,
                    clean=clean,
                    local_close_owner=close_owned,
                )
        return YandexSessionResult(websocket.close_code, websocket.close_code == 1000, close_owned)
