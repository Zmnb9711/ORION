"""SpeechKit v3 chunks for exact finalized English text; no provider rewriting."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4
from typing import Any

from orion.yandex_speechkit_v3_proto import tts_pb2
from orion.full_voice_timing import observe

# Generated protobuf classes are installed dynamically by the official runtime.
p: Any = tts_pb2


def protected_stream_requests(text: str) -> tuple:
    if not isinstance(text, str) or not text or text.isspace() or len(text) > 4096:
        raise ValueError("invalid_protected_text")
    return (
        p.StreamSynthesisRequest(options=p.SynthesisOptions(
            voice="john", speed=1.0,
            output_audio_spec=p.AudioFormatOptions(raw_audio=p.RawAudio(
                audio_encoding=p.RawAudio.LINEAR16_PCM, sample_rate_hertz=48000,
            )),
        )),
        p.StreamSynthesisRequest(synthesis_input=p.SynthesisInput(text=text)),
        p.StreamSynthesisRequest(force_synthesis=p.ForceSynthesisEvent()),
    )


class ProtectedStreamingTts:
    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._call = None
        self._closed = False
        self.observation_turn_id = None

    async def synthesize(self, text, language, tx_id, observer=None) -> bytes:
        raise RuntimeError("streaming_tts_requires_explicit_stream_boundary")

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if self._closed or self._call is not None:
            raise RuntimeError("streaming_tts_unavailable")
        requests = protected_stream_requests(text)
        assert requests[1].synthesis_input.text == text
        import grpc
        channel = grpc.aio.secure_channel(
            "tts.api.cloud.yandex.net:443", grpc.ssl_channel_credentials(),
            options=(("grpc.max_receive_message_length", 1048576), ("grpc.enable_retries", 0)),
        )
        count = 0
        try:
            method = channel.stream_stream(
                "/speechkit.tts.v3.Synthesizer/StreamSynthesis",
                request_serializer=p.StreamSynthesisRequest.SerializeToString,
                response_deserializer=p.StreamSynthesisResponse.FromString,
            )
            observe("T6", self.observation_turn_id)
            self._call = method(
                iter(requests), timeout=15.0, wait_for_ready=False,
                metadata=(("authorization", "Api-Key " + self._key), ("x-client-request-id", str(uuid4()))),
            )
            async for response in self._call:
                chunk = bytes(response.audio_chunk.data)
                if not chunk:
                    continue
                count += len(chunk)
                if len(chunk) % 2 or count > 2_880_000:
                    raise RuntimeError("streaming_tts_pcm_bound")
                yield chunk
            if not count:
                raise RuntimeError("streaming_tts_empty")
        except grpc.aio.AioRpcError as exc:
            raise RuntimeError("streaming_tts_" + exc.code().name.lower()) from None
        finally:
            if self._call is not None:
                self._call.cancel()
            self._call = None
            await channel.close()

    async def aclose(self) -> None:
        self._closed = True
        if self._call is not None:
            self._call.cancel()
