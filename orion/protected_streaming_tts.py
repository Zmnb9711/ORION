"""SpeechKit v3 chunks for exact finalized English text; no provider rewriting."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from uuid import uuid4
from typing import Any
import time
import hashlib
import re
import asyncio

from orion.yandex_speechkit_v3_proto import tts_pb2

# Generated protobuf classes are installed dynamically by the official runtime.
p: Any = tts_pb2
# Finite envelope allowance for the existing <=30-second / 2,880,000-byte PCM
# contract. One SpeechKit message may contain the entire clip plus text fields.
GRPC_RECEIVE_LIMIT = 3 * 1024 * 1024


def safe_rpc_failure(code: str, details: str | None) -> dict:
    """Only recognize a closed gRPC diagnostic grammar, never log provider prose."""
    detail = details or ""
    if detail.startswith("Stream removed (") and detail.endswith(")"):
        detail = detail[len("Stream removed ("):-1]
    match = re.fullmatch(r"(?:CLIENT: )?Received message larger than max \((\d{1,12}) vs\.? (\d{1,12})\)", detail)
    if code == "RESOURCE_EXHAUSTED" and match:
        actual, limit = map(int, match.groups())
        return {"failure_stage": "TTS_GRPC_CLIENT_ERROR", "failure_category": "TTS_GRPC_CLIENT_LIMIT",
                "rpc_origin": "LOCAL_CLIENT_LIMIT", "rpc_details": f"Received message larger than max ({actual} vs {limit})",
                "rejected_message_bytes": actual, "grpc_receive_limit": limit}
    return {"failure_stage": "TTS_RPC", "failure_category": "TTS_PROVIDER_RESOURCE_EXHAUSTED"
            if code == "RESOURCE_EXHAUSTED" else "TIMEOUT" if code == "DEADLINE_EXCEEDED" else "TTS_PROVIDER_OTHER_ERROR",
            "rpc_origin": "UNDETERMINED", "rpc_details": "unrecognized detail withheld"}


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
        self.observe_diagnostic: Callable[..., None] = lambda _event, **_fields: None

    def _diagnostic(self, event, **fields):
        try:
            self.observe_diagnostic(event, monotonic=time.monotonic(), **fields)
        except Exception:
            pass  # Optional observation never affects synthesis or cleanup.

    async def synthesize(self, text, language, tx_id, observer=None) -> bytes:
        raise RuntimeError("streaming_tts_requires_explicit_stream_boundary")

    def _requests(self, text: str) -> tuple:
        """Internal builder seam; the protected default is unchanged."""
        return protected_stream_requests(text)

    async def stream(self, text: str) -> AsyncGenerator[bytes, None]:
        if self._closed or self._call is not None:
            raise RuntimeError("streaming_tts_unavailable")
        try:
            requests = self._requests(text)
        except (ValueError, TypeError):
            self._diagnostic("tts_request_failed", failure_stage="TTS_REQUEST", failure_category="TTS_REQUEST_ERROR")
            raise
        assert requests[1].synthesis_input.text == text
        import grpc
        channel = grpc.aio.secure_channel(
            "tts.api.cloud.yandex.net:443", grpc.ssl_channel_credentials(),
            options=(("grpc.max_receive_message_length", GRPC_RECEIVE_LIMIT), ("grpc.enable_retries", 0)),
        )
        count = 0
        messages = largest = 0
        request_id = str(uuid4())
        try:
            method = channel.stream_stream(
                "/speechkit.tts.v3.Synthesizer/StreamSynthesis",
                request_serializer=p.StreamSynthesisRequest.SerializeToString,
                response_deserializer=p.StreamSynthesisResponse.FromString,
            )
            self._diagnostic("tts_rpc_start", tts_request_id=request_id,
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), text_chars=len(text),
                text_utf8_bytes=len(text.encode("utf-8")), grpc_receive_limit=GRPC_RECEIVE_LIMIT,
                grpc_send_limit=-1, request_message_bytes=max(r.ByteSize() for r in requests))
            self._call = method(
                iter(requests), timeout=15.0, wait_for_ready=False,
                metadata=(("authorization", "Api-Key " + self._key), ("x-client-request-id", request_id)),
            )
            first_response = True
            async for response in self._call:
                messages += 1
                message_bytes = response.ByteSize()
                largest = max(largest, message_bytes)
                if first_response:
                    self._diagnostic("tts_provider_response", tts_request_id=request_id)
                    first_response = False
                chunk = bytes(response.audio_chunk.data)
                if not chunk:
                    continue
                count += len(chunk)
                if messages <= 64:
                    self._diagnostic("tts_pcm_message", tts_request_id=request_id, message_index=messages,
                        message_bytes=message_bytes, pcm_chunk_bytes=len(chunk), tts_pcm_bytes=count)
                if len(chunk) % 2 or count > 2_880_000:
                    raise RuntimeError("streaming_tts_pcm_bound")
                yield chunk
            if not count:
                raise RuntimeError("streaming_tts_empty")
            self._diagnostic("tts_rpc_completed", tts_request_id=request_id)
        except grpc.aio.AioRpcError as exc:
            self._diagnostic("tts_rpc_failed", tts_request_id=request_id,
                             error_class=type(exc).__name__, rpc_code=exc.code().name,
                             **safe_rpc_failure(exc.code().name, exc.details()))
            raise RuntimeError("streaming_tts_" + exc.code().name.lower()) from None
        except BaseException as exc:
            category = ("CANCELLED" if isinstance(exc, asyncio.CancelledError) else
                        "PRESENTATION_ABORT" if isinstance(exc, GeneratorExit) else
                        "TTS_NO_PCM" if str(exc) == "streaming_tts_empty" else
                        "TTS_PARTIAL_STREAM_FAILURE" if count else "UNKNOWN_DELIVERY_FAILURE")
            self._diagnostic("tts_stream_failed", tts_request_id=request_id,
                failure_stage="TTS", failure_category=category, error_class=type(exc).__name__)
            raise
        finally:
            if self._call is not None:
                self._call.cancel()
            self._call = None
            await channel.close()
            self._diagnostic("tts_rpc_closed", tts_request_id=request_id,
                provider_message_count=messages, largest_message_bytes=largest, tts_pcm_bytes=count,
                cleanup_complete=True)

    async def aclose(self) -> None:
        self._closed = True
        if self._call is not None:
            self._call.cancel()
