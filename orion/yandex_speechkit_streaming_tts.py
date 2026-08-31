"""Experimental SpeechKit v3 StreamSynthesis adapter with neutral PCM output."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Callable

from orion.radio_streaming import StreamingPcmEvent
from orion.yandex_speechkit_v3_proto import tts_pb2


SPEECHKIT_STREAM_TTS_ENDPOINT = "tts.api.cloud.yandex.net:443"
SPEECHKIT_STREAM_TTS_RPC = "/speechkit.tts.v3.Synthesizer/StreamSynthesis"
SPEECHKIT_STREAM_TTS_RATE_HZ = 48_000
SPEECHKIT_STREAM_TTS_VOICE = "jane"
SPEECHKIT_STREAM_TTS_ROLE = "neutral"
SPEECHKIT_STREAM_TTS_SPEED = 1.0
SPEECHKIT_STREAM_TTS_TIMEOUT_S = 35.0


class SpeechKitTtsOutputMode(StrEnum):
    REST_BUFFERED = "speechkit_rest"
    STREAMING_V3 = "speechkit_v3_streaming"


def speechkit_stream_options() -> Any:
    """Exact configuration proven by the isolated StreamSynthesis probe."""

    return tts_pb2.SynthesisOptions(  # type: ignore[attr-defined]
        voice=SPEECHKIT_STREAM_TTS_VOICE,
        role=SPEECHKIT_STREAM_TTS_ROLE,
        speed=SPEECHKIT_STREAM_TTS_SPEED,
        output_audio_spec=tts_pb2.AudioFormatOptions(  # type: ignore[attr-defined]
            raw_audio=tts_pb2.RawAudio(  # type: ignore[attr-defined]
                audio_encoding=tts_pb2.RawAudio.LINEAR16_PCM,  # type: ignore[attr-defined]
                sample_rate_hertz=SPEECHKIT_STREAM_TTS_RATE_HZ,
            )
        ),
    )


def speechkit_stream_requests(text: str) -> tuple[Any, ...]:
    finalized = text.strip()
    if not finalized or len(finalized) > 5_000:
        raise ValueError("SpeechKit streaming text must contain 1 to 5000 characters")
    return (
        tts_pb2.StreamSynthesisRequest(  # type: ignore[attr-defined]
            options=speechkit_stream_options()
        ),
        tts_pb2.StreamSynthesisRequest(  # type: ignore[attr-defined]
            synthesis_input=tts_pb2.SynthesisInput(text=finalized)  # type: ignore[attr-defined]
        ),
        tts_pb2.StreamSynthesisRequest(  # type: ignore[attr-defined]
            force_synthesis=tts_pb2.ForceSynthesisEvent()  # type: ignore[attr-defined]
        ),
    )


class SpeechKitStreamingTtsClient:
    """One fresh, cancellation-safe bidirectional RPC per finalized response."""

    async def stream(
        self,
        text: str,
        api_key: str,
        *,
        response_id: str,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> AsyncIterator[StreamingPcmEvent]:
        key = api_key.strip()
        if not key:
            raise ValueError("Yandex API key is required")
        requests = speechkit_stream_requests(text)
        import grpc

        channel: Any = grpc.aio.secure_channel(
            SPEECHKIT_STREAM_TTS_ENDPOINT,
            grpc.ssl_channel_credentials(),
            options=(("grpc.enable_retries", 0),),
        )
        call: Any = None
        cancellation_watch: asyncio.Task[None] | None = None
        chunk_index = 0
        try:
            method = channel.stream_stream(
                SPEECHKIT_STREAM_TTS_RPC,
                request_serializer=tts_pb2.StreamSynthesisRequest.SerializeToString,  # type: ignore[attr-defined]
                response_deserializer=tts_pb2.StreamSynthesisResponse.FromString,  # type: ignore[attr-defined]
            )
            call = method(
                iter(requests),
                metadata=(
                    ("authorization", f"Api-Key {key}"),
                    ("x-client-request-id", str(uuid.uuid4())),
                ),
                timeout=SPEECHKIT_STREAM_TTS_TIMEOUT_S,
                wait_for_ready=False,
            )

            async def watch_cancellation() -> None:
                while not cancelled():
                    await asyncio.sleep(0.05)
                call.cancel()

            cancellation_watch = asyncio.create_task(watch_cancellation())
            async for response in call:
                if cancelled():
                    call.cancel()
                    yield StreamingPcmEvent(
                        response_id=response_id,
                        pcm=b"",
                        sample_rate_hz=SPEECHKIT_STREAM_TTS_RATE_HZ,
                        channels=1,
                        sample_width_bytes=2,
                        chunk_index=chunk_index,
                        cancelled=True,
                    )
                    return
                payload = bytes(response.audio_chunk.data)
                if not payload:
                    continue
                yield StreamingPcmEvent(
                    response_id=response_id,
                    pcm=payload,
                    sample_rate_hz=SPEECHKIT_STREAM_TTS_RATE_HZ,
                    channels=1,
                    sample_width_bytes=2,
                    chunk_index=chunk_index,
                )
                chunk_index += 1
            yield StreamingPcmEvent(
                response_id=response_id,
                pcm=b"",
                sample_rate_hz=SPEECHKIT_STREAM_TTS_RATE_HZ,
                channels=1,
                sample_width_bytes=2,
                chunk_index=chunk_index,
                end_of_stream=True,
            )
        except grpc.aio.AioRpcError as exc:
            if cancelled():
                yield StreamingPcmEvent(
                    response_id=response_id,
                    pcm=b"",
                    sample_rate_hz=SPEECHKIT_STREAM_TTS_RATE_HZ,
                    channels=1,
                    sample_width_bytes=2,
                    chunk_index=chunk_index,
                    cancelled=True,
                )
                return
            detail = _safe_provider_detail(exc.details() or "", key)
            yield StreamingPcmEvent(
                response_id=response_id,
                pcm=b"",
                sample_rate_hz=SPEECHKIT_STREAM_TTS_RATE_HZ,
                channels=1,
                sample_width_bytes=2,
                chunk_index=chunk_index,
                error=f"{exc.code().name}: {detail}"[:300],
            )
        finally:
            if cancellation_watch is not None:
                cancellation_watch.cancel()
                await asyncio.gather(cancellation_watch, return_exceptions=True)
            if call is not None and cancelled():
                call.cancel()
            await channel.close()


def _safe_provider_detail(value: str, secret: str) -> str:
    safe = value.replace(secret, "<redacted>") if secret else value
    safe = re.sub(r"[\x00-\x1f\x7f]+", " ", safe)
    return re.sub(r"\s+", " ", safe).strip()[:240]
