"""Optional streaming output behind unchanged Stage 7C ingress/fidelity policy."""

from __future__ import annotations

import asyncio
import time

from orion.bounded_radio_stream import BoundedPcmStream
from orion.protected_presentation import (
    ProtectedPresentationService, PresentationResult, PresentationFailure,
)
from orion.protected_streaming_tts import ProtectedStreamingTts
from orion.full_voice_timing import observe
from orion.radio_contracts import RadioTransmissionRequest, StreamingPcmAudio
from orion.srs_resampler import StreamingPcm16Resampler


class StreamingProtectedPresentation(ProtectedPresentationService):
    """Inherits exact structured validation, dedupe and lifetime identity bounds."""

    def __init__(self, tts: ProtectedStreamingTts, router, *, transport_id="srs") -> None:
        super().__init__(tts, router, transport_id=transport_id)
        self.streaming_tts = tts
        self.marks: dict[str, float | int] = {}
        self._streams: dict[str, BoundedPcmStream] = {}

    async def _run(self, finalized, context, operation) -> PresentationResult:
        tx = str(context.tx_correlation_id)
        stream = BoundedPcmStream()
        self._streams[tx] = stream
        producer = None
        self.marks = {"presentation_started": time.monotonic()}
        result = PresentationResult(tx, "failed", True, PresentationFailure.TTS_ERROR)

        async def produce() -> None:
            resampler = StreamingPcm16Resampler(48000, 44100)
            self.streaming_tts.observation_turn_id = context.turn_id
            self.marks["tts_started"] = time.monotonic()
            observe("T5", context.turn_id)
            total = 0
            try:
                async for chunk in self.streaming_tts.stream(finalized.text):
                    if "tts_first_pcm" not in self.marks:
                        observe("T7", context.turn_id)
                    self.marks.setdefault("tts_first_pcm", time.monotonic())
                    total += len(chunk)
                    normalized = resampler.process(chunk)
                    if normalized:
                        await asyncio.to_thread(stream.feed, normalized)
                self.marks["tts_completed"] = time.monotonic()
                tail = resampler.process(b"", end_of_input=True)
                if tail:
                    await asyncio.to_thread(stream.feed, tail)
                self.marks["tts_pcm_bytes"] = total
                stream.finish()
            except BaseException:
                stream.abort("protected_tts_failed_or_cancelled")
                raise
            finally:
                resampler.reset()

        try:
            request = RadioTransmissionRequest(
                context=context, audio=StreamingPcmAudio(stream=stream),
                transport_id=self._transport, timeout_s=self._radio_timeout,
            )
            operation.accepted = True  # A throwing submit may already have acted.
            submitted = self._router.submit(request)
            operation.accepted = submitted.accepted
            if not submitted.accepted:
                result = PresentationResult(tx, "failed", True, PresentationFailure.RADIO_REJECTED)
                return result
            producer = asyncio.create_task(produce(), name="protected-stream-producer")
            deadline = time.monotonic() + self._radio_timeout
            while time.monotonic() < deadline:
                snapshot = self._router.get(tx)
                if snapshot is None:
                    raise RuntimeError("radio_identity_lost")
                result = self._snapshot(snapshot)
                if result.terminal:
                    if result.state == "completed":
                        await producer
                    break
                await asyncio.sleep(.01)
            else:
                stream.abort("radio_deadline")
                result = PresentationResult(tx, "unknown", False, PresentationFailure.RADIO_TIMEOUT)
        except asyncio.CancelledError:
            stream.abort()
            result = PresentationResult(tx, "cancelled", not operation.accepted, PresentationFailure.CANCELLED)
        except Exception:
            stream.abort("presentation_failed")
            result = PresentationResult(tx, "failed", False, PresentationFailure.TTS_ERROR)
        finally:
            stream.abort("presentation_terminal")
            if producer is not None:
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            self._streams.pop(tx, None)
            self.marks["presentation_terminal"] = time.monotonic()
            self.marks["pcm_buffer_high_water"] = stream.high_water
            operation.result = result
        return result

    async def cancel(self, tx: str) -> PresentationResult:
        if tx in self._streams:
            self._streams[tx].abort()
        return await super().cancel(tx)
