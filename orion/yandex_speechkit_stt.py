"""Persistent Yandex SpeechKit v3 STT for physical radio transmissions.

The adapter owns provider protocol state only. SRS owns physical transmission
boundaries and the semantic pipeline consumes ``FinalizedUserUtterance``.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable, Protocol

from orion.realtime_audio_transport import (
    FinalizedUserUtterance,
    RealtimeInputTransmissionCompleted,
    RealtimeInputTransmissionStarted,
    RealtimePcmEndpoint,
)
from orion.realtime_test_evidence import realtime_test_evidence
from orion.yandex_speechkit_v3_proto import stt_pb2

SPEECHKIT_STT_ENDPOINT = "stt.api.cloud.yandex.net:443"
SPEECHKIT_STT_RPC = "/speechkit.stt.v3.Recognizer/RecognizeStreaming"
SPEECHKIT_STT_MODEL = "general"
SPEECHKIT_STT_RATE_HZ = 16_000
SPEECHKIT_STT_LANGUAGE = "ru-RU"
SPEECHKIT_CLOSE_TIMEOUT_S = 2.0


class SpeechKitSttState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    TURN_ACTIVE = "turn_active"
    WAITING_FINAL = "waiting_final"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


class SpeechKitSttProtocolError(RuntimeError):
    """The provider stream no longer has unambiguous physical-turn ownership."""


@dataclass(frozen=True, slots=True)
class SpeechKitProviderEvent:
    kind: str
    session_uuid: str = ""
    transcript: str = ""
    final_index: int = 0
    received_data_ms: int = 0
    final_time_ms: int = 0
    eou_time_ms: int = 0
    response_wall_time_ms: int = 0
    status: str = ""


class SpeechKitStreamingPort(Protocol):
    async def open(self, api_key: str) -> None: ...

    async def send_audio(self, pcm16le: bytes) -> None: ...

    async def send_eou(self) -> None: ...

    async def receive(self) -> SpeechKitProviderEvent | None: ...

    async def done_writing(self) -> None: ...

    async def close(self) -> None: ...


class SessionDiagnostics(Protocol):
    def record(self, event: str, **fields: object) -> None: ...


def speechkit_session_options() -> stt_pb2.StreamingOptions:
    """Return the exact External-EOU configuration proven by the live probes."""

    return stt_pb2.StreamingOptions(
        recognition_model=stt_pb2.RecognitionModelOptions(
            model=SPEECHKIT_STT_MODEL,
            audio_format=stt_pb2.AudioFormatOptions(
                raw_audio=stt_pb2.RawAudio(
                    audio_encoding=stt_pb2.RawAudio.LINEAR16_PCM,
                    sample_rate_hertz=SPEECHKIT_STT_RATE_HZ,
                    audio_channel_count=1,
                )
            ),
            text_normalization=stt_pb2.TextNormalizationOptions(
                text_normalization=(
                    stt_pb2.TextNormalizationOptions.TEXT_NORMALIZATION_DISABLED
                ),
                profanity_filter=False,
                literature_text=False,
                phone_formatting_mode=(
                    stt_pb2.TextNormalizationOptions.PHONE_FORMATTING_MODE_DISABLED
                ),
            ),
            language_restriction=stt_pb2.LanguageRestrictionOptions(
                restriction_type=stt_pb2.LanguageRestrictionOptions.WHITELIST,
                language_code=[SPEECHKIT_STT_LANGUAGE],
            ),
            audio_processing_type=stt_pb2.RecognitionModelOptions.REAL_TIME,
        ),
        eou_classifier=stt_pb2.EouClassifierOptions(
            external_classifier=stt_pb2.ExternalEouClassifier()
        ),
    )


class GrpcSpeechKitStreamingPort:
    """Thin generated-protobuf transport; all turn policy stays in the adapter."""

    def __init__(self) -> None:
        self._grpc: Any = None
        self._channel: Any = None
        self._call: Any = None
        self._opened = False
        self._writing_done = False

    async def open(self, api_key: str) -> None:
        if self._opened:
            raise SpeechKitSttProtocolError("SpeechKit stream is already open")
        key = api_key.strip()
        if not key:
            raise ValueError("Yandex API key is required")
        import grpc

        self._grpc = grpc
        self._channel = grpc.aio.secure_channel(
            SPEECHKIT_STT_ENDPOINT,
            grpc.ssl_channel_credentials(),
        )
        method = self._channel.stream_stream(
            SPEECHKIT_STT_RPC,
            request_serializer=stt_pb2.StreamingRequest.SerializeToString,
            response_deserializer=stt_pb2.StreamingResponse.FromString,
        )
        self._call = method(
            metadata=(
                ("authorization", f"Api-Key {key}"),
                ("x-client-request-id", str(uuid.uuid4())),
            )
        )
        await self._call.write(
            stt_pb2.StreamingRequest(session_options=speechkit_session_options())
        )
        self._opened = True

    async def send_audio(self, pcm16le: bytes) -> None:
        call = self._require_call(writable=True)
        await call.write(
            stt_pb2.StreamingRequest(chunk=stt_pb2.AudioChunk(data=pcm16le))
        )

    async def send_eou(self) -> None:
        call = self._require_call(writable=True)
        await call.write(stt_pb2.StreamingRequest(eou=stt_pb2.Eou()))

    async def receive(self) -> SpeechKitProviderEvent | None:
        call = self._require_call()
        response = await call.read()
        assert self._grpc is not None
        if response is self._grpc.aio.EOF:
            return None
        kind = response.WhichOneof("Event") or "provider_event"
        transcript = ""
        if kind in {"partial", "final"}:
            alternatives = getattr(response, kind).alternatives
            if alternatives:
                transcript = alternatives[0].text
        status = ""
        if kind == "status_code":
            status = stt_pb2.CodeType.Name(response.status_code.code_type)
        cursors = response.audio_cursors
        return SpeechKitProviderEvent(
            kind=kind,
            session_uuid=response.session_uuid.uuid,
            transcript=transcript,
            final_index=cursors.final_index,
            received_data_ms=cursors.received_data_ms,
            final_time_ms=cursors.final_time_ms,
            eou_time_ms=cursors.eou_time_ms,
            response_wall_time_ms=response.response_wall_time_ms,
            status=status,
        )

    async def done_writing(self) -> None:
        if self._call is None or self._writing_done:
            return
        self._writing_done = True
        await self._call.done_writing()

    async def close(self) -> None:
        channel = self._channel
        self._channel = None
        self._call = None
        if channel is not None:
            await channel.close()

    def _require_call(self, *, writable: bool = False) -> Any:
        if self._call is None or not self._opened or (
            writable and self._writing_done
        ):
            raise SpeechKitSttProtocolError("SpeechKit stream is not writable")
        return self._call


@dataclass(slots=True)
class _PhysicalTurn:
    transmission_id: str
    started_at: float
    pcm_bytes: int = 0
    pcm_chunks: int = 0
    capture_enabled: bool = False
    last_input_write_timestamp: str | None = None
    last_input_write_monotonic_ns: int | None = None
    eou_sent: bool = False
    terminal_final_seen: bool = False
    final_text: str | None = None
    final_index: int | None = None
    session_uuid: str = ""
    received_data_ms: int | None = None
    final_time_ms: int | None = None
    eou_time_ms: int | None = None
    eou_update_seen: bool = False


class SpeechKitV3RadioSttAdapter:
    """Map SRS packet turns and authoritative TX ends to External-EOU turns."""

    provider_id = "speechkit_v3"

    def __init__(
        self,
        api_key: str,
        endpoint: RealtimePcmEndpoint,
        stop_event: threading.Event,
        diagnostics: SessionDiagnostics,
        *,
        port_factory: Callable[[], SpeechKitStreamingPort] = GrpcSpeechKitStreamingPort,
        on_streaming: Callable[[], None] | None = None,
        on_session_ready: Callable[[str], None] | None = None,
        on_finalized_utterance: Callable[[FinalizedUserUtterance], None] | None = None,
    ) -> None:
        if endpoint.pcm_format.sample_rate != SPEECHKIT_STT_RATE_HZ:
            raise ValueError("SpeechKit STT requires 16000 Hz input PCM")
        if endpoint.pcm_format.channels != 1:
            raise ValueError("SpeechKit STT requires mono input PCM")
        if endpoint.pcm_format.sample_width_bytes != 2:
            raise ValueError("SpeechKit STT requires signed 16-bit input PCM")
        self._api_key = api_key
        self._endpoint = endpoint
        self._stop = stop_event
        self._diagnostics = diagnostics
        self._port_factory = port_factory
        self._on_streaming = on_streaming or (lambda: None)
        self._on_session_ready = on_session_ready or (lambda _session_id: None)
        self._on_finalized = on_finalized_utterance or (lambda _utterance: None)
        self._state = SpeechKitSttState.DISCONNECTED
        self._active: _PhysicalTurn | None = None
        self._pending: _PhysicalTurn | None = None
        self._provider_session_uuid = ""
        self._last_final_index: int | None = None
        self._accepting_finals = False
        self._local_session_id = f"speechkit-v3-{uuid.uuid4().hex}"

    @property
    def state(self) -> SpeechKitSttState:
        return self._state

    async def run(self) -> None:
        port = self._port_factory()
        receiver_task: asyncio.Task[None] | None = None
        opened = False
        self._state = SpeechKitSttState.CONNECTING
        try:
            await port.open(self._api_key)
            opened = True
            self._accepting_finals = True
            self._state = SpeechKitSttState.READY
            self._diagnostics.record(
                "speechkit_stt_session_ready",
                stt_provider=self.provider_id,
                session_options_count=1,
                sample_rate_hz=SPEECHKIT_STT_RATE_HZ,
                external_eou=True,
            )
            self._endpoint.start()
            self._on_session_ready(self._local_session_id)
            self._on_streaming()
            receiver_task = asyncio.create_task(
                self._receive_worker(port),
                name="orion-speechkit-stt-receive",
            )
            while not self._stop.is_set():
                if receiver_task.done():
                    error = receiver_task.exception()
                    if error is not None:
                        raise error
                    raise ConnectionError("SpeechKit provider stream closed unexpectedly")
                item = await asyncio.to_thread(self._endpoint.read_input, 0.05)
                if item is None:
                    failure = self._endpoint.failure()
                    if failure is not None:
                        raise failure
                    continue
                if isinstance(item, RealtimeInputTransmissionStarted):
                    self._start_turn(item)
                elif isinstance(item, RealtimeInputTransmissionCompleted):
                    await self._complete_turn(port, item)
                else:
                    await self._send_pcm(port, item)
            failure = self._endpoint.failure()
            if failure is not None:
                raise failure
        except Exception as exc:
            self._state = SpeechKitSttState.ERROR
            self._diagnostics.record(
                "speechkit_stt_provider_error",
                stt_provider=self.provider_id,
                error_type=type(exc).__name__,
            )
            raise
        finally:
            self._accepting_finals = False
            self._active = None
            self._pending = None
            if self._state is not SpeechKitSttState.ERROR:
                self._state = SpeechKitSttState.CLOSING
            self._endpoint.stop()
            if opened:
                try:
                    await port.done_writing()
                    if receiver_task is not None and not receiver_task.done():
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(receiver_task),
                                timeout=SPEECHKIT_CLOSE_TIMEOUT_S,
                            )
                        except asyncio.TimeoutError:
                            receiver_task.cancel()
                finally:
                    if receiver_task is not None and not receiver_task.done():
                        receiver_task.cancel()
                    if receiver_task is not None:
                        await asyncio.gather(receiver_task, return_exceptions=True)
                    await port.close()
            self._api_key = ""
            if self._state is not SpeechKitSttState.ERROR:
                self._state = SpeechKitSttState.CLOSED

    def _start_turn(self, marker: RealtimeInputTransmissionStarted) -> None:
        if self._state is not SpeechKitSttState.READY:
            raise SpeechKitSttProtocolError(
                "New local SpeechKit turn arrived while the provider barrier is pending"
            )
        if self._active is not None or self._pending is not None:
            raise SpeechKitSttProtocolError("SpeechKit physical-turn ownership is ambiguous")
        self._active = _PhysicalTurn(
            marker.transmission_id,
            time.monotonic(),
            capture_enabled=realtime_test_evidence.begin_speechkit_stt_input(
                marker.transmission_id
            ),
        )
        self._state = SpeechKitSttState.TURN_ACTIVE
        self._diagnostics.record(
            "speechkit_stt_ptt_started",
            stt_provider=self.provider_id,
            physical_transmission_id=marker.transmission_id,
            srs_packet_turn_id=marker.transmission_id,
            capture_enabled=self._active.capture_enabled,
        )

    async def _send_pcm(self, port: SpeechKitStreamingPort, pcm16le: bytes) -> None:
        turn = self._active
        if self._state is not SpeechKitSttState.TURN_ACTIVE or turn is None:
            raise SpeechKitSttProtocolError("SpeechKit PCM arrived outside an active PTT")
        if not pcm16le or len(pcm16le) % 2:
            raise ValueError("SpeechKit input PCM is empty or not int16-aligned")
        if turn.capture_enabled and not realtime_test_evidence.append_speechkit_stt_input(
            turn.transmission_id,
            pcm16le,
        ):
            turn.capture_enabled = False
        await port.send_audio(pcm16le)
        turn.pcm_bytes += len(pcm16le)
        turn.pcm_chunks += 1
        turn.last_input_write_timestamp = datetime.now(UTC).isoformat(
            timespec="microseconds"
        )
        turn.last_input_write_monotonic_ns = time.monotonic_ns()

    async def _complete_turn(
        self,
        port: SpeechKitStreamingPort,
        marker: RealtimeInputTransmissionCompleted,
    ) -> None:
        turn = self._active
        if self._state is not SpeechKitSttState.TURN_ACTIVE or turn is None:
            raise SpeechKitSttProtocolError("SpeechKit PTT completion has no active turn")
        if marker.transmission_id != turn.transmission_id:
            raise SpeechKitSttProtocolError("SpeechKit PTT completion identity mismatch")
        if turn.eou_sent:
            raise SpeechKitSttProtocolError("SpeechKit EOU was already sent for this PTT")
        if turn.pcm_bytes <= 0:
            raise SpeechKitSttProtocolError("SpeechKit PTT completed without decoded PCM")
        await port.send_eou()
        turn.eou_sent = True
        self._active = None
        self._pending = turn
        self._state = SpeechKitSttState.WAITING_FINAL
        eou_sent_timestamp = datetime.now(UTC).isoformat(timespec="microseconds")
        eou_sent_monotonic_ns = time.monotonic_ns()
        if (
            turn.last_input_write_monotonic_ns is not None
            and eou_sent_monotonic_ns <= turn.last_input_write_monotonic_ns
        ):
            # Preserve causal ordering when the Windows monotonic clock has a
            # coarser observable resolution than these adjacent operations.
            eou_sent_monotonic_ns = turn.last_input_write_monotonic_ns + 1
        artifact_included = False
        if turn.capture_enabled:
            artifact_included = realtime_test_evidence.finalize_speechkit_stt_input(
                turn.transmission_id,
                expected_pcm_bytes=turn.pcm_bytes,
            )
        self._diagnostics.record(
            "speechkit_stt_eou_sent",
            stt_provider=self.provider_id,
            physical_transmission_id=turn.transmission_id,
            srs_packet_turn_id=turn.transmission_id,
            byte_count=turn.pcm_bytes,
            speechkit_pcm_bytes_before_eou=turn.pcm_bytes,
            chunk_count=turn.pcm_chunks,
            eou_count=1,
            eou_sent_timestamp=eou_sent_timestamp,
            eou_sent_monotonic_ns=eou_sent_monotonic_ns,
            last_input_write_timestamp=turn.last_input_write_timestamp,
            last_input_write_monotonic_ns=turn.last_input_write_monotonic_ns,
            capture_enabled=turn.capture_enabled,
            artifact_included=artifact_included,
            first_accepted_packet_timestamp=(
                marker.first_accepted_packet_timestamp
            ),
            last_accepted_packet_timestamp=marker.last_accepted_packet_timestamp,
            accepted_packet_count=marker.accepted_packet_count,
            first_packet_id=marker.first_packet_id,
            last_packet_id=marker.last_packet_id,
            sequence_gap_count=marker.sequence_gap_count,
            decode_error_count=marker.decode_error_count,
            decoded_pcm_bytes=marker.decoded_pcm_bytes,
            padding_bytes=marker.padding_bytes,
            framed_pcm_bytes=marker.framed_pcm_bytes,
            packet_quiescence_completed_timestamp=(
                marker.packet_quiescence_completed_timestamp
            ),
            boundary_gap_ms=marker.boundary_gap_ms,
            boundary=marker.boundary,
            srs_tx_started_timestamp=marker.srs_tx_started_timestamp,
            srs_tx_ended_timestamp=marker.srs_tx_ended_timestamp,
            srs_tx_sending_on=marker.srs_tx_sending_on,
            srs_tx_state_authoritative=marker.srs_tx_state_authoritative,
            eou_triggered_by_7082=marker.srs_tx_state_authoritative,
            decoded_plus_padding_matches_framed=(
                marker.decoded_pcm_bytes + marker.padding_bytes
                == marker.framed_pcm_bytes
                if marker.decoded_pcm_bytes is not None
                and marker.padding_bytes is not None
                and marker.framed_pcm_bytes is not None
                else None
            ),
            framed_matches_speechkit=(
                marker.framed_pcm_bytes == turn.pcm_bytes
                if marker.framed_pcm_bytes is not None
                else None
            ),
        )

    async def _receive_worker(self, port: SpeechKitStreamingPort) -> None:
        while True:
            event = await port.receive()
            if event is None:
                return
            self._accept_session_identity(event)
            if event.kind == "final":
                self._accept_final(event)
            elif event.kind == "eou_update":
                self._accept_eou_update(event)
            elif event.kind == "partial":
                self._diagnostics.record(
                    "speechkit_stt_partial",
                    stt_provider=self.provider_id,
                    characters=len(event.transcript),
                    final_index=event.final_index,
                )
            elif event.kind == "status_code":
                self._diagnostics.record(
                    "speechkit_stt_provider_status",
                    stt_provider=self.provider_id,
                    status=event.status,
                    final_index=event.final_index,
                )

    def _accept_session_identity(self, event: SpeechKitProviderEvent) -> None:
        session_uuid = event.session_uuid.strip()
        if not session_uuid:
            return
        if self._provider_session_uuid and session_uuid != self._provider_session_uuid:
            raise SpeechKitSttProtocolError("SpeechKit session UUID changed within one RPC")
        self._provider_session_uuid = session_uuid

    def _accept_final(self, event: SpeechKitProviderEvent) -> None:
        turn = self._pending
        if not self._accepting_finals or self._stop.is_set():
            event_name = (
                "speechkit_stt_empty_final_ignored"
                if not event.transcript.strip()
                else "speechkit_stt_late_final_ignored"
            )
            self._diagnostics.record(
                event_name,
                stt_provider=self.provider_id,
                final_index=event.final_index,
                closing=True,
            )
            return
        if self._state is not SpeechKitSttState.WAITING_FINAL or turn is None:
            raise SpeechKitSttProtocolError("Terminal SpeechKit FINAL has no pending PTT")
        if turn.terminal_final_seen:
            raise SpeechKitSttProtocolError("Multiple terminal FINALs mapped to one PTT")
        if self._last_final_index is not None and event.final_index <= self._last_final_index:
            raise SpeechKitSttProtocolError("SpeechKit final_index did not advance")
        if turn.final_index is not None and event.final_index != turn.final_index:
            raise SpeechKitSttProtocolError("SpeechKit FINAL/EOU_UPDATE index mismatch")
        turn.terminal_final_seen = True
        turn.final_text = event.transcript
        turn.final_index = event.final_index
        turn.session_uuid = event.session_uuid or self._provider_session_uuid
        turn.received_data_ms = event.received_data_ms
        turn.final_time_ms = event.final_time_ms
        if event.transcript.strip():
            self._diagnostics.record(
                "speechkit_stt_final",
                stt_provider=self.provider_id,
                physical_transmission_id=turn.transmission_id,
                speechkit_session_uuid=turn.session_uuid,
                final_index=event.final_index,
                received_data_ms=event.received_data_ms,
                final_time_ms=event.final_time_ms,
                characters=len(event.transcript),
                response_wall_time_ms=event.response_wall_time_ms,
                terminal_final_observed=True,
                final_text_empty=False,
            )
        else:
            self._diagnostics.record(
                "speechkit_stt_empty_final_observed",
                stt_provider=self.provider_id,
                physical_transmission_id=turn.transmission_id,
                final_index=event.final_index,
                received_data_ms=event.received_data_ms,
                final_time_ms=event.final_time_ms,
                terminal_final_observed=True,
                final_text_empty=True,
            )
        self._finalize_if_complete(turn)

    def _accept_eou_update(self, event: SpeechKitProviderEvent) -> None:
        turn = self._pending
        if not self._accepting_finals or self._stop.is_set():
            self._diagnostics.record(
                "speechkit_stt_closing_eou_update",
                stt_provider=self.provider_id,
                final_index=event.final_index,
            )
            return
        if self._state is not SpeechKitSttState.WAITING_FINAL or turn is None:
            raise SpeechKitSttProtocolError("SpeechKit EOU_UPDATE has no pending PTT")
        if turn.eou_update_seen:
            raise SpeechKitSttProtocolError("Duplicate SpeechKit EOU_UPDATE for one PTT")
        if turn.final_index is not None and event.final_index != turn.final_index:
            raise SpeechKitSttProtocolError("SpeechKit FINAL/EOU_UPDATE index mismatch")
        turn.eou_update_seen = True
        turn.final_index = event.final_index
        turn.session_uuid = event.session_uuid or self._provider_session_uuid
        turn.received_data_ms = event.received_data_ms
        turn.final_time_ms = event.final_time_ms
        turn.eou_time_ms = event.eou_time_ms
        self._diagnostics.record(
            "speechkit_stt_eou_update",
            stt_provider=self.provider_id,
            physical_transmission_id=turn.transmission_id,
            speechkit_session_uuid=turn.session_uuid,
            final_index=event.final_index,
            received_data_ms=event.received_data_ms,
            final_time_ms=event.final_time_ms,
            eou_time_ms=event.eou_time_ms,
            response_wall_time_ms=event.response_wall_time_ms,
        )
        self._finalize_if_complete(turn)

    def _finalize_if_complete(self, turn: _PhysicalTurn) -> None:
        if not turn.terminal_final_seen or not turn.eou_update_seen:
            return
        if turn.final_index is None:
            raise SpeechKitSttProtocolError("SpeechKit final barrier has no final_index")
        if not (
            turn.received_data_ms == turn.final_time_ms == turn.eou_time_ms
        ):
            raise SpeechKitSttProtocolError("SpeechKit External-EOU cursor barrier mismatch")
        if self._pending is not turn:
            raise SpeechKitSttProtocolError("SpeechKit pending-turn identity changed")
        final_text = turn.final_text or ""
        final_text_empty = not final_text.strip()
        self._pending = None
        self._last_final_index = turn.final_index
        self._state = SpeechKitSttState.READY
        self._diagnostics.record(
            "speechkit_stt_barrier_completed",
            stt_provider=self.provider_id,
            physical_transmission_id=turn.transmission_id,
            speechkit_session_uuid=turn.session_uuid or self._local_session_id,
            final_index=turn.final_index,
            barrier_completed=True,
            final_text_empty=final_text_empty,
            utterance_emitted=not final_text_empty,
        )
        if final_text_empty:
            return
        provider_session_id = turn.session_uuid or self._local_session_id
        event_id = f"speechkit-final-{provider_session_id}-{turn.final_index}"
        provider_item_id = f"speechkit-item-{provider_session_id}-{turn.final_index}"
        utterance = FinalizedUserUtterance(
            transmission_id=turn.transmission_id,
            transcript=final_text,
            provider_id=self.provider_id,
            provider_session_id=provider_session_id,
            provider_final_index=turn.final_index,
            event_id=event_id,
            provider_item_id=provider_item_id,
            finalized_at=time.monotonic(),
        )
        realtime_test_evidence.record_transcript(
            "user",
            final_text,
            turn_id=turn.transmission_id,
            event_id=event_id,
            provider_item_id=provider_item_id,
        )
        self._diagnostics.record(
            "speechkit_stt_utterance_finalized",
            stt_provider=self.provider_id,
            physical_transmission_id=turn.transmission_id,
            speechkit_session_uuid=provider_session_id,
            final_index=turn.final_index,
            finalized_utterance_emitted=True,
        )
        if not self._stop.is_set() and self._accepting_finals:
            self._on_finalized(utterance)
