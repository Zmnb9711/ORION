"""Provider-only Yandex Realtime PCM session.

This module owns the Yandex WebSocket and provider event lifecycle. It has no
PortAudio, SRS, codec, device, EAM, DCS, or tool dependency.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from orion.flight_context import FlightContextUpdateGate
from orion.realtime_audio_transport import (
    RealtimeInputTransmissionCompleted,
    RealtimeInputTransmissionStarted,
    RealtimePcmEndpoint,
    RealtimeTranscriptSegment,
)
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
from orion.yandex_presentation import (
    YandexPresentationSessionDriver,
    yandex_presentation,
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
        on_session_ready: Callable[[str], None] | None = None,
        flight_context_gate: FlightContextUpdateGate | None = None,
        interaction_state: RealtimeInteractionState | None = None,
        on_user_transcript_segment: Callable[[RealtimeTranscriptSegment], None]
        | None = None,
        on_input_transmission_started: Callable[[str, int], None] | None = None,
        on_input_transmission_completed: Callable[[str, int], None] | None = None,
        on_provider_input_activity: Callable[[int | None], None] | None = None,
        suppress_provider_responses: Callable[[], bool] | None = None,
    ) -> None:
        self._api_key = api_key
        self._folder_id = folder_id
        self._endpoint = endpoint
        self._stop = stop_event
        self._diagnostics = diagnostics
        self._on_streaming = on_streaming or (lambda: None)
        self._on_session_ready = on_session_ready or (lambda _session_id: None)
        self._flight_context = flight_context_gate or FlightContextUpdateGate(
            YANDEX_INSTRUCTIONS
        )
        self._interaction = interaction_state or RealtimeInteractionState()
        self._on_user_transcript_segment = on_user_transcript_segment or (
            lambda _segment: None
        )
        self._on_input_transmission_started = on_input_transmission_started or (
            lambda _transmission_id, _provider_audio_ms: None
        )
        self._on_input_transmission_completed = on_input_transmission_completed or (
            lambda _transmission_id, _provider_audio_ms: None
        )
        self._on_provider_input_activity = on_provider_input_activity or (
            lambda _provider_audio_ms: None
        )
        self._suppress_provider_responses = suppress_provider_responses or (
            lambda: False
        )

    async def _send_flight_context_update(
        self,
        websocket: Any,
        *,
        force: bool = False,
        presentation_idle: bool = True,
    ) -> bool:
        deferred_before = self._flight_context.deferred_count
        coalesced_before = self._flight_context.coalesced_count
        update = self._flight_context.next_update(
            force=force,
            safe_to_apply=force or (
                presentation_idle and self._interaction.safe_to_refresh
            ),
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
        await websocket.send_json(
            yandex_session_update(
                instructions=update.instructions,
            )
        )
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
        presentation_task: asyncio.Task[None] | None = None
        presentation_driver: YandexPresentationSessionDriver | None = None
        close_owned = False
        suppressed_response_ids: set[str] = set()
        provider_segment_started_ms: int | None = None
        provider_segment_spans: deque[
            tuple[str | None, int | None, int | None]
        ] = deque()

        def provider_audio_ms(event: dict[str, Any], key: str) -> int | None:
            value = event.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        async def send_worker() -> None:
            input_frames_sent = 0
            while not self._stop.is_set():
                await self._send_flight_context_update(
                    websocket,
                    presentation_idle=(
                        presentation_driver is None or not presentation_driver.active
                    ),
                )
                pcm = await asyncio.to_thread(self._endpoint.read_input, 0.1)
                if pcm is None:
                    continue
                provider_position_ms = round(
                    input_frames_sent * 1000 / self._endpoint.pcm_format.sample_rate
                )
                if isinstance(pcm, RealtimeInputTransmissionStarted):
                    self._diagnostics.record(
                        "input_transmission_started",
                        physical_transmission_id=pcm.transmission_id,
                        provider_position_ms=provider_position_ms,
                    )
                    try:
                        self._on_input_transmission_started(
                            pcm.transmission_id, provider_position_ms
                        )
                    except Exception as exc:
                        self._diagnostics.record(
                            "input_transmission_observer_failed",
                            error_type=type(exc).__name__,
                        )
                    continue
                if isinstance(pcm, RealtimeInputTransmissionCompleted):
                    self._diagnostics.record(
                        "input_transmission_completed",
                        physical_transmission_id=pcm.transmission_id,
                        provider_position_ms=provider_position_ms,
                        boundary=pcm.boundary,
                        provider_commit_requested=False,
                    )
                    try:
                        self._on_input_transmission_completed(
                            pcm.transmission_id, provider_position_ms
                        )
                    except Exception as exc:
                        self._diagnostics.record(
                            "input_transmission_observer_failed",
                            error_type=type(exc).__name__,
                        )
                    continue
                if len(pcm) % 2:
                    raise ValueError("Provider input PCM is not aligned to int16 samples")
                await websocket.send_json(encode_yandex_input_audio(pcm))
                frame_bytes = (
                    self._endpoint.pcm_format.channels
                    * self._endpoint.pcm_format.sample_width_bytes
                )
                input_frames_sent += len(pcm) // frame_bytes

        latest_speech_stopped_at: float | None = None

        async def receive_worker() -> None:
            latest_response_id: str | None = None
            nonlocal provider_segment_started_ms, latest_speech_stopped_at
            while not self._stop.is_set():
                message = await websocket.receive()
                if message.type is aiohttp.WSMsgType.TEXT:
                    event = message.json()
                    kind = str(event.get("type") or "")
                    probe_error_consumed = (
                        presentation_driver.handle_event(event)
                        if presentation_driver is not None
                        else False
                    )
                    if kind == "input_audio_buffer.speech_started":
                        provider_segment_started_ms = provider_audio_ms(
                            event, "audio_start_ms"
                        )
                        turn_id = self._interaction.speech_started()
                        self._endpoint.input_speech_started()
                        self._on_provider_input_activity(provider_segment_started_ms)
                        self._diagnostics.record(
                            "provider_segment_speech_started",
                            turn_id=turn_id,
                            provider_start_ms=provider_segment_started_ms,
                        )
                    elif kind == "input_audio_buffer.speech_stopped":
                        turn_id = self._interaction.speech_stopped()
                        latest_speech_stopped_at = time.monotonic()
                        audio_end_ms = provider_audio_ms(event, "audio_end_ms")
                        provider_segment_spans.append(
                            (turn_id, provider_segment_started_ms, audio_end_ms)
                        )
                        provider_segment_started_ms = None
                        self._on_provider_input_activity(audio_end_ms)
                        self._diagnostics.record(
                            "provider_segment_speech_stopped",
                            turn_id=turn_id,
                            provider_end_ms=audio_end_ms,
                        )
                    elif kind == "conversation.item.input_audio_transcription.completed":
                        transcript = str(event.get("transcript") or "")
                        segment_turn_id, audio_start_ms, audio_end_ms = (
                            provider_segment_spans.popleft()
                            if provider_segment_spans
                            else (None, None, None)
                        )
                        turn_id = (
                            segment_turn_id or self._interaction.current_turn_id()
                        )
                        event_id = str(event.get("event_id") or "")
                        provider_item_id = str(event.get("item_id") or "")
                        realtime_test_evidence.record_transcript(
                            "user",
                            transcript,
                            turn_id=turn_id,
                            event_id=event_id,
                            provider_item_id=provider_item_id,
                        )
                        self._diagnostics.record(
                            "transcription_segment_completed",
                            turn_id=turn_id,
                            provider_item_id=provider_item_id,
                            characters=len(transcript),
                            provider_start_ms=audio_start_ms,
                            provider_end_ms=audio_end_ms,
                            persisted=False,
                        )
                        try:
                            self._on_user_transcript_segment(
                                RealtimeTranscriptSegment(
                                    transcript=transcript,
                                    turn_id=turn_id,
                                    event_id=event_id,
                                    provider_item_id=provider_item_id,
                                    speech_stopped_at=latest_speech_stopped_at,
                                    provider_audio_start_ms=audio_start_ms,
                                    provider_audio_end_ms=audio_end_ms,
                                )
                            )
                        except Exception as exc:
                            self._diagnostics.record(
                                "transcript_segment_consumer_failed",
                                error_type=type(exc).__name__,
                            )
                        self._on_provider_input_activity(audio_end_ms)
                        if self._suppress_provider_responses():
                            self._interaction.complete_current_turn_without_response()
                    elif kind == "input_audio_buffer.committed":
                        self._on_provider_input_activity(None)
                        self._diagnostics.record(
                            kind,
                            turn_id=self._interaction.current_turn_id(),
                            provider_item_id=str(event.get("item_id") or ""),
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
                        if self._suppress_provider_responses():
                            turn_id = self._interaction.current_turn_id()
                            suppressed_response_ids.add(response_id)
                            self._diagnostics.record(
                                "provider_response_suppressed",
                                response_id=response_id,
                                turn_id=turn_id,
                                provider_media_generated=False,
                                provider_media_reached_transport=False,
                            )
                            await websocket.send_json(
                                {
                                    "type": "response.cancel",
                                    "response_id": response_id,
                                }
                            )
                            self._diagnostics.record(
                                "provider_response_cancel_requested",
                                response_id=response_id,
                                turn_id=turn_id,
                            )
                            continue
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
                        if response_id in suppressed_response_ids:
                            self._diagnostics.record(
                                "provider_suppressed_pcm_generated",
                                response_id=response_id,
                                byte_count=len(pcm),
                                provider_media_generated=True,
                                provider_media_reached_transport=False,
                            )
                            continue
                        first_audio = self._interaction.first_audio(response_id)
                        if first_audio is not None:
                            realtime_test_evidence.record_probe_first_audio(response_id)
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
                        if response_id in suppressed_response_ids:
                            self._diagnostics.record(
                                "provider_suppressed_audio_ignored",
                                response_id=response_id,
                                provider_media_reached_transport=False,
                            )
                            continue
                        self._endpoint.response_audio_done(response_id)
                        self._diagnostics.record("audio_done", response_id=response_id)
                    elif kind in {
                        "response.output_audio_transcript.done",
                        "response.output_text.done",
                    }:
                        response_id = str(
                            event.get("response_id") or latest_response_id or "unknown"
                        )
                        if response_id in suppressed_response_ids:
                            self._diagnostics.record(
                                "provider_suppressed_text_ignored",
                                response_id=response_id,
                                characters=len(
                                    str(event.get("transcript") or event.get("text") or "")
                                ),
                            )
                            continue
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
                        if response_id in suppressed_response_ids:
                            suppressed_response_ids.discard(response_id)
                            self._diagnostics.record(
                                "provider_suppressed_response_done",
                                response_id=response_id,
                                status=status,
                                provider_media_reached_transport=False,
                            )
                            continue
                        self._endpoint.response_done(response_id, status)
                        turn_id = self._interaction.response_done(response_id)
                        self._diagnostics.record(
                            "response_done",
                            response_id=response_id,
                            turn_id=turn_id,
                            status=status,
                        )
                    elif kind == "error":
                        if not probe_error_consumed:
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
            yandex_session_id: str | None = None
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
                        session = event.get("session") or {}
                        candidate_id = str(session.get("id") or "")
                        if candidate_id:
                            yandex_session_id = candidate_id
                        self._diagnostics.record(
                            kind or "handshake_event",
                            provider_event_id=str(event.get("event_id") or ""),
                        )
                        if kind == "session.updated":
                            break
                        if kind == "error":
                            raise RuntimeError(event.get("error") or "Yandex provider error")
                    else:
                        raise ConnectionError("Yandex closed before session.updated")
                if not self._stop.is_set():
                    if not yandex_session_id:
                        raise RuntimeError("Yandex session.updated did not expose a session ID")
                    self._on_session_ready(yandex_session_id)
                    presentation_driver = YandexPresentationSessionDriver(
                        yandex_presentation,
                        yandex_session_id=yandex_session_id,
                        diagnostics=self._diagnostics,
                        interaction_idle=lambda: self._interaction.safe_to_refresh,
                    )
                    self._endpoint.start()
                    self._on_streaming()
                    send_task = asyncio.create_task(send_worker(), name="orion-yandex-send")
                    receive_task = asyncio.create_task(
                        receive_worker(), name="orion-yandex-receive"
                    )
                    presentation_task = asyncio.create_task(
                        presentation_driver.run(websocket, self._stop),
                        name="orion-yandex-presentation",
                    )
                    while True:
                        failure = self._endpoint.failure()
                        if failure is not None:
                            raise failure
                        if self._stop.is_set():
                            break
                        await asyncio.sleep(0.05)
                        for task in (send_task, receive_task, presentation_task):
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
                if presentation_driver is not None:
                    presentation_driver.close()
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
                if presentation_task is not None and not presentation_task.done():
                    presentation_task.cancel()
                    try:
                        await presentation_task
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
