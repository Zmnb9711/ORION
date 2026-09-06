"""Isolated input transcription: no audio output, tools, Core or radio callbacks."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import json
import re
import time
from typing import Any, Literal
from uuid import UUID

import aiohttp

from orion.yandex_realtime_provider import (
    build_yandex_url,
    encode_yandex_input_audio,
    yandex_authorization_headers,
    yandex_session_update,
)

MAX_PCM_BYTES = 882_000
MAX_TRANSCRIPT_CHARS = 4_000
MAX_EVENT_BYTES = 262_144
MAX_TOTAL_EVENT_BYTES = 4_194_304
MAX_EVENTS = 1024
FINAL_INPUT_EVENT = "conversation.item.input_audio_transcription.completed"
PARTIAL_INPUT_EVENT = "conversation.item.input_audio_transcription.delta"
PROVIDER_ID = "yandex.realtime.input-transcription"
_FINAL_SETTLE_S = 0.100
_CLOSE_TIMEOUT_S = 2.0
_monotonic = time.monotonic


def _latencies(marks: dict[str, float]) -> dict[str, float]:
    pairs = {
        "connection_setup_latency_ms": ("connection_started", "connection_ready"),
        "audio_submission_duration_ms": ("first_audio_sent", "last_audio_sent"),
        "stt_finalize_latency_ms": ("last_audio_sent", "final_transcript_received"),
        "cleanup_latency_ms": ("cleanup_started", "cleanup_completed"),
        "total_operation_latency_ms": ("connection_started", "cleanup_completed"),
    }
    return {
        name: (marks[end] - marks[start]) * 1000
        for name, (start, end) in pairs.items()
        if start in marks and end in marks
    }


class SttFailure(StrEnum):
    INVALID_AUDIO = "invalid_audio"
    AUDIO_TOO_LARGE = "audio_too_large"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    CONNECTION_ERROR = "connection_error"
    AUTH_ERROR = "auth_error"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_ERROR = "provider_error"
    FINAL_TRANSCRIPT_TIMEOUT = "final_transcript_timeout"
    EMPTY_FINAL_TRANSCRIPT = "empty_final_transcript"
    TRANSCRIPT_TOO_LARGE = "transcript_too_large"
    CONFLICTING_FINAL_TRANSCRIPT = "conflicting_final_transcript"
    CANCELLED = "cancelled"
    SHUTTING_DOWN = "shutting_down"
    BUSY = "busy"
    INVALID_OPERATION = "invalid_operation"


class _Rejected(Exception):
    def __init__(self, code: SttFailure):
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class FinalTranscript:
    interaction_id: UUID
    text: str = field(repr=False)
    input_language: str
    provider_id: str
    provider_item_id: str | None
    started_at: datetime
    finalized_at: datetime
    final: Literal[True] = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.interaction_id, UUID)
            or not isinstance(self.text, str)
            or not self.text.strip()
            or len(self.text) > MAX_TRANSCRIPT_CHARS
            or self.input_language != "ru-RU"
            or self.final is not True
            or self.started_at.utcoffset() is None
            or self.finalized_at.utcoffset() is None
            or self.finalized_at < self.started_at
        ):
            raise ValueError("Invalid final transcript contract")


@dataclass(frozen=True, slots=True)
class SttResult:
    transcript: FinalTranscript | None = None
    failure: SttFailure | None = None
    session_closed_cleanly: bool = True

    def __post_init__(self) -> None:
        if (self.transcript is None) == (self.failure is None):
            raise ValueError("Exactly one STT outcome is required")


class _FinalCollector:
    """Only the input-final event can supply text; sealed operations ignore late data."""

    def __init__(self) -> None:
        self.text: str | None = None
        self.item: str | None = None
        self.sealed = False

    def accept(self, event: dict[str, Any]) -> bool:
        if self.sealed or event.get("type") != FINAL_INPUT_EVENT:
            return False
        text = event.get("transcript")
        if not isinstance(text, str):
            raise _Rejected(SttFailure.PROVIDER_ERROR)
        if not text.strip():
            raise _Rejected(SttFailure.EMPTY_FINAL_TRANSCRIPT)
        if len(text) > MAX_TRANSCRIPT_CHARS:
            raise _Rejected(SttFailure.TRANSCRIPT_TOO_LARGE)
        item = event.get("item_id")
        if item is not None and (
            not isinstance(item, str)
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", item)
        ):
            raise _Rejected(SttFailure.PROVIDER_ERROR)
        if self.text is not None:
            if (self.text, self.item) != (text, item):
                raise _Rejected(SttFailure.CONFLICTING_FINAL_TRANSCRIPT)
            return False
        self.text, self.item = text, item
        return True


def _provider_failure(event: dict[str, Any]) -> SttFailure:
    error = event.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if code in (
        "unauthorized",
        "unauthenticated",
        "permission_denied",
        "invalid_api_key",
    ):
        return SttFailure.AUTH_ERROR
    if code in ("invalid_request_error", "invalid_argument"):
        return SttFailure.PROVIDER_REJECTED
    return SttFailure.PROVIDER_ERROR


class YandexRealtimeSttAdapter:
    """Single event-loop owner, one active operation; fresh session, no audio retries."""

    def __init__(self, api_key: str, folder_id: str, *, deadline_s: float = 15.0):
        if not 0 < deadline_s <= 15.0:
            raise ValueError("Invalid STT deadline")
        # Existing validated auth/URL helpers, without loading settings or credentials here.
        try:
            self._url = build_yandex_url(folder_id)
            self._headers = yandex_authorization_headers(api_key)
        except Exception:
            raise ValueError("Invalid STT configuration") from None
        self._deadline_s = deadline_s
        self._stopped = False
        self._active: asyncio.Task[SttResult] | None = None
        self._events: deque[dict[str, object]] = deque(maxlen=128)

    def diagnostics(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(event) for event in self._events)

    def _record(self, turn: UUID, category: str, **numbers: int | float | bool) -> None:
        self._events.append(
            {
                "interaction_id": turn.hex,
                "category": category,
                "monotonic_s": _monotonic(),
                **numbers,
            }
        )

    async def transcribe(
        self,
        pcm: bytes | bytearray | memoryview,
        interaction_id: UUID,
        *,
        input_language: str = "ru-RU",
        sample_rate_hz: int = 44100,
        channels: int = 1,
        sample_width_bytes: int = 2,
        cancellation: asyncio.Event | None = None,
    ) -> SttResult:
        if self._stopped:
            return SttResult(failure=SttFailure.SHUTTING_DOWN)
        if cancellation is not None and cancellation.is_set():
            return SttResult(failure=SttFailure.CANCELLED)
        if self._active is not None:
            return SttResult(failure=SttFailure.BUSY)
        if not isinstance(interaction_id, UUID):
            return SttResult(failure=SttFailure.INVALID_OPERATION)
        if input_language != "ru-RU":
            return SttResult(failure=SttFailure.UNSUPPORTED_LANGUAGE)
        if not isinstance(pcm, (bytes, bytearray, memoryview)) or (
            sample_rate_hz,
            channels,
            sample_width_bytes,
        ) != (44100, 1, 2):
            return SttResult(failure=SttFailure.INVALID_AUDIO)
        try:
            size = pcm.nbytes if isinstance(pcm, memoryview) else len(pcm)
        except ValueError:  # A released memoryview is not admissible audio.
            return SttResult(failure=SttFailure.INVALID_AUDIO)
        if size > MAX_PCM_BYTES:
            return SttResult(failure=SttFailure.AUDIO_TOO_LARGE)
        if size == 0 or size % 2:
            return SttResult(failure=SttFailure.INVALID_AUDIO)
        try:
            audio = bytes(
                pcm
            )  # Snapshot mutable caller buffers once; never truncate/resample.
        except Exception:
            return SttResult(failure=SttFailure.INVALID_AUDIO)
        task = asyncio.create_task(self._operate(audio, interaction_id))
        self._active = task
        watcher = None
        try:
            if cancellation is not None:
                watcher = asyncio.create_task(cancellation.wait())
                await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
                if cancellation.is_set():
                    task.cancel()
                    return await self._cancelled_result(task)
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            return await self._cancelled_result(task)
        finally:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            self._active = None

    @staticmethod
    async def _cancelled_result(task: asyncio.Task[SttResult]) -> SttResult:
        outcomes = await asyncio.gather(task, return_exceptions=True)
        outcome = outcomes[0]
        clean = (
            outcome.session_closed_cleanly if isinstance(outcome, SttResult) else True
        )
        return SttResult(failure=SttFailure.CANCELLED, session_closed_cleanly=clean)

    async def _operate(self, audio: bytes, turn: UUID) -> SttResult:
        started = datetime.now(UTC)
        collector = _FinalCollector()
        client: Any = None
        websocket: Any = None
        transcript: FinalTranscript | None = None
        failure: SttFailure | None = None
        clean = True
        count = total = 0
        receiver: asyncio.Task[dict[str, Any]] | None = None
        marks: dict[str, float] = {}
        final_at: datetime | None = None
        generated_counts = {
            "generated_audio_events": 0,
            "generated_text_events": 0,
            "tool_request_events": 0,
            "generated_other_events": 0,
        }

        def mark(name: str) -> None:
            marks[name] = _monotonic()
            self._record(turn, name, monotonic_s=marks[name])

        mark("connection_started")
        self._record(turn, "operation_started", audio_bytes=len(audio))

        async def receive() -> dict[str, Any]:
            nonlocal count, total
            message = await websocket.receive()
            if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}:
                if collector.text is not None and websocket.close_code in (1000, 1001):
                    return {"type": "_normal_remote_close"}
                raise _Rejected(SttFailure.CONNECTION_ERROR)
            if message.type != aiohttp.WSMsgType.TEXT:
                raise _Rejected(SttFailure.CONNECTION_ERROR)
            if not isinstance(message.data, str):
                raise _Rejected(SttFailure.PROVIDER_ERROR)
            size = len(message.data.encode("utf-8"))
            count += 1
            total += size
            if (
                size > MAX_EVENT_BYTES
                or total > MAX_TOTAL_EVENT_BYTES
                or count > MAX_EVENTS
            ):
                raise _Rejected(SttFailure.PROVIDER_ERROR)
            event = json.loads(message.data)
            if not isinstance(event, dict):
                raise _Rejected(SttFailure.PROVIDER_ERROR)
            if event.get("type") == "error":
                raise _Rejected(_provider_failure(event))
            return event

        async def send_audio() -> None:
            # Match the existing 20 ms input framing; no padding or synthesized silence.
            for offset in range(0, len(audio), 1764):
                await websocket.send_json(
                    encode_yandex_input_audio(audio[offset : offset + 1764])
                )
                if offset == 0:
                    mark("first_audio_sent")
                if offset + 1764 >= len(audio):
                    mark("last_audio_sent")
                await asyncio.sleep(
                    0
                )  # Cancellation/event fairness, not a replay/pacing engine.
            self._record(turn, "audio_submitted", audio_bytes=len(audio))

        try:
            async with asyncio.timeout(self._deadline_s):
                client = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=None, connect=4.0)
                )
                websocket = await client.ws_connect(
                    self._url,
                    headers=dict(self._headers),
                    heartbeat=20.0,
                    autoclose=True,
                    max_msg_size=MAX_EVENT_BYTES,
                )
                self._record(turn, "connected")
                await websocket.send_json(
                    yandex_session_update(
                        instructions="Recognize the supplied Russian speech. No operational authority or tools are available."
                    )
                )
                while True:
                    event = await receive()
                    if event.get("type") == "session.updated":
                        break
                    if event.get("type") == FINAL_INPUT_EVENT:
                        raise _Rejected(SttFailure.PROVIDER_ERROR)  # No audio sent yet.
                    self._record(turn, "setup_event_dropped")
                self._record(turn, "session_ready")
                mark("connection_ready")
                await send_audio()
                settle_until: float | None = None
                while True:
                    if collector.text is not None and settle_until is None:
                        settle_until = (
                            asyncio.get_running_loop().time() + _FINAL_SETTLE_S
                        )
                    if settle_until is None:
                        event = await receive()
                    else:
                        remaining = settle_until - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            break
                        receiver = asyncio.create_task(receive())
                        done, _ = await asyncio.wait((receiver,), timeout=remaining)
                        if not done:
                            # Do not cancel aiohttp.receive: that poisons close_code
                            # with 1006. Owned close wakes/drains it during cleanup.
                            break
                        event = receiver.result()
                        receiver = None
                    kind = event.get("type")
                    if kind == "_normal_remote_close":
                        self._record(turn, "normal_remote_close")
                        break
                    if kind == FINAL_INPUT_EVENT:
                        first = collector.accept(event)
                        if first:
                            mark("final_transcript_received")
                            final_at = datetime.now(UTC)
                        self._record(
                            turn,
                            "input_final" if first else "duplicate_final",
                            characters=len(collector.text or ""),
                        )
                    elif kind == "conversation.item.input_audio_transcription.failed":
                        raise _Rejected(SttFailure.PROVIDER_ERROR)
                    elif kind == PARTIAL_INPUT_EVENT:
                        self._record(turn, "input_partial_dropped")
                    elif isinstance(kind, str) and (
                        kind.startswith("response.")
                        or kind.startswith("conversation.item.")
                    ):
                        # Never decode generated audio, execute tools, or forward assistant text.
                        bucket = (
                            "tool_request_events"
                            if "function_call" in kind or "tool" in kind
                            else "generated_text_events"
                            if "text" in kind or "transcript" in kind
                            else "generated_audio_events"
                            if "audio" in kind
                            else "generated_other_events"
                        )
                        generated_counts[bucket] += 1
                        self._record(turn, "generated_or_item_event_dropped")
                    else:
                        self._record(turn, "lifecycle_event_dropped")
                collector.sealed = True
                assert collector.text is not None
                transcript = FinalTranscript(
                    turn,
                    collector.text,
                    "ru-RU",
                    PROVIDER_ID,
                    collector.item,
                    started,
                    final_at or datetime.now(UTC),
                )
        except asyncio.CancelledError:
            failure = SttFailure.CANCELLED
        except TimeoutError:
            failure = SttFailure.FINAL_TRANSCRIPT_TIMEOUT
        except _Rejected as exc:
            failure = exc.code
        except aiohttp.ClientResponseError as exc:
            failure = (
                SttFailure.AUTH_ERROR
                if exc.status in (401, 403)
                else SttFailure.PROVIDER_REJECTED
            )
        except aiohttp.ClientConnectionError:
            failure = SttFailure.CONNECTION_ERROR
        except Exception:
            failure = SttFailure.PROVIDER_ERROR
        finally:
            collector.sealed = True
            mark("cleanup_started")

            async def cleanup() -> bool:
                # Shield this bounded owner from caller cancellation. Always close
                # HTTP even when WebSocket handshake times out or raises.
                close_warning = False
                try:
                    if websocket is not None:
                        async with asyncio.timeout(_CLOSE_TIMEOUT_S):
                            await websocket.close(code=1000)
                except (Exception, asyncio.CancelledError):
                    close_warning = True
                try:
                    if client is not None:
                        async with asyncio.timeout(_CLOSE_TIMEOUT_S):
                            await client.close()
                except (Exception, asyncio.CancelledError):
                    close_warning = True
                # Real aiohttp.close wakes receive; a broken/fake peer may not.
                # Cancel/drain only AFTER owned transport/session closure.
                if receiver is not None:
                    if not receiver.done():
                        receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
                ws_closed = websocket is None or bool(websocket.closed)
                http_closed = client is None or bool(client.closed)
                reader_done = receiver is None or receiver.done()
                close_code = (
                    int(websocket.close_code or 0) if websocket is not None else 0
                )
                self._record(
                    turn,
                    "resources_closed",
                    websocket_closed=ws_closed,
                    http_session_closed=http_closed,
                    receive_task_done=reader_done,
                    send_task_done=True,
                    close_code=close_code,
                    close_warning=close_warning or close_code not in (0, 1000, 1001),
                )
                return ws_closed and http_closed and reader_done

            cleanup_task = asyncio.create_task(cleanup())
            while True:
                try:
                    clean = await asyncio.shield(cleanup_task)
                    break
                except asyncio.CancelledError:
                    failure = SttFailure.CANCELLED
            mark("cleanup_completed")
            self._record(turn, "latency_metrics", **_latencies(marks))
            self._record(turn, "generated_output_discard_counts", **generated_counts)
        if failure is None and not clean:
            failure = SttFailure.PROVIDER_ERROR
        self._record(
            turn,
            failure.value if failure else "completed",
            session_closed_cleanly=clean,
        )
        return SttResult(None if failure else transcript, failure, clean)

    async def shutdown(self) -> bool:
        self._stopped = True
        self._headers.clear()
        task = self._active
        if task is not None:
            task.cancel()
            try:
                async with asyncio.timeout(5.0):
                    result = await asyncio.shield(task)
                return result.session_closed_cleanly
            except (Exception, asyncio.CancelledError):
                return False
        return True
