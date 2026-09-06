"""Persistent Yandex SpeechKit v3 STT for physical radio transmissions.

Recovery transport port adapted from 42520a57 (provider messages only).
No turn coordinator, semantic authority or automatic provider retries live here.
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
            options=(("grpc.max_receive_message_length", 65536),),
        )
        method = self._channel.stream_stream(
            SPEECHKIT_STT_RPC,
            request_serializer=stt_pb2.StreamingRequest.SerializeToString,
            response_deserializer=stt_pb2.StreamingResponse.FromString,
        )
        self._call = method(
            timeout=300.0,
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
        if self._call is not None:
            self._call.cancel()
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
