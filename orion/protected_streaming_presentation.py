"""Optional streaming output behind unchanged Stage 7C ingress/fidelity policy."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from orion.bounded_radio_stream import BoundedPcmStream
from orion.protected_presentation import (
    ProtectedPresentationService, PresentationResult, PresentationFailure,
)
from orion.protected_streaming_tts import ProtectedStreamingTts
from orion.radio_contracts import RadioTransmissionRequest, StreamingPcmAudio
from orion.srs_resampler import StreamingPcm16Resampler


def stream_failure(code: str | None, phase: str) -> dict:
    """Closed local reason vocabulary; never log arbitrary exception prose."""
    categories = {
        "srs_collision_or_unexpected_origin": ("SRS_RX_GUARD", "SRS_TRANSPORT_FAILURE"),
        "physical_evidence_unavailable": ("SRS_RX_GUARD", "SRS_TRANSPORT_FAILURE"),
        "stream_backpressure_timeout": ("PCM_STREAM", "PCM_BACKPRESSURE_FAILURE"),
        "stream_tx_failed": ("PCM_CONSUMER", "PCM_CONSUMER_FAILURE"),
        "streaming_tts_empty": ("TTS", "TTS_NO_PCM"),
        "streaming_tts_pcm_bound": ("TTS", "TTS_PARTIAL_STREAM_FAILURE"),
        "stream_closed_or_excessive": ("PCM_STREAM", "PCM_STREAM_ERROR"),
        "stream_cancelled": ("PRESENTATION", "CANCELLED"),
        "radio_deadline": ("PRESENTATION", "TIMEOUT"),
        "presentation_failed": ("PRESENTATION", "PRESENTATION_ABORT"),
        "stream_prebuffer_timeout": ("PCM_CONSUMER", "TIMEOUT"),
    }
    stage, category = categories.get(code or "", (phase, "PCM_PRODUCER_FAILURE" if phase == "PCM_PRODUCER" else "UNKNOWN_DELIVERY_FAILURE"))
    return {"failure_stage": stage, "failure_category": category,
            "safe_error_code": code if code in categories else "unrecognized_local_error"}


class StreamingProtectedPresentation(ProtectedPresentationService):
    """Inherits exact structured validation, dedupe and lifetime identity bounds."""

    def __init__(self, tts: ProtectedStreamingTts, router, *, transport_id="srs") -> None:
        super().__init__(tts, router, transport_id=transport_id)
        self.streaming_tts = tts
        self.marks: dict[str, float | int] = {}
        self._streams: dict[str, BoundedPcmStream] = {}
        self.observe_diagnostic: Callable[..., None] = lambda _event, **_fields: None

    def _diagnostic(self, event, **fields):
        try:
            self.observe_diagnostic(event, monotonic=time.monotonic(), **fields)
        except Exception:
            pass  # Evidence is not a condition of an accepted transmission.

    async def _run(self, finalized, context, operation) -> PresentationResult:
        tx = str(context.tx_correlation_id)
        stream = BoundedPcmStream()
        self._streams[tx] = stream
        producer = None
        self.marks = {"presentation_started": time.monotonic()}
        result = PresentationResult(tx, "failed", True, PresentationFailure.TTS_ERROR)

        async def produce() -> None:
            self._diagnostic("tts_producer_start", tx_id=tx)
            resampler = StreamingPcm16Resampler(48000, 44100)
            self.marks["tts_started"] = time.monotonic()
            total = 0
            phase = "TTS"
            audio = self.streaming_tts.stream(finalized.text)
            try:
                async for chunk in audio:
                    if "tts_first_pcm" not in self.marks:
                        self._diagnostic("tts_first_pcm", tx_id=tx)
                    self.marks.setdefault("tts_first_pcm", time.monotonic())
                    total += len(chunk)
                    self.marks["tts_pcm_bytes"] = total
                    phase = "PCM_PRODUCER"
                    normalized = resampler.process(chunk)
                    if normalized:
                        await asyncio.to_thread(stream.feed, normalized)
                    phase = "TTS"
                self.marks["tts_completed"] = time.monotonic()
                tail = resampler.process(b"", end_of_input=True)
                if tail:
                    await asyncio.to_thread(stream.feed, tail)
                self.marks["tts_pcm_bytes"] = total
                stream.finish()
            except BaseException as exc:
                self._diagnostic("tts_stream_abort", tx_id=tx, error_class=type(exc).__name__,
                    stream_abort_reason="protected_tts_failed_or_cancelled", tts_pcm_bytes=total,
                    **stream_failure(stream.first_abort_code or ("stream_cancelled" if isinstance(exc, asyncio.CancelledError) else str(exc)), phase))
                stream.abort("protected_tts_failed_or_cancelled")
                raise
            finally:
                try:
                    # A feed/consumer failure occurs outside the suspended TTS
                    # generator. Close it explicitly; do not wait for GC to
                    # release its gRPC call before the next independent turn.
                    await audio.aclose()
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
            self._diagnostic("radio_admission", tx_id=tx, status="accepted" if submitted.accepted else "rejected",
                failure_stage=None if submitted.accepted else "RADIO_ADMISSION",
                failure_category=None if submitted.accepted else "RADIO_ADMISSION_REJECTED")
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
            first_abort = stream.first_abort_code
            stream.abort("presentation_terminal")
            if producer is not None:
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            self._streams.pop(tx, None)
            self.marks["presentation_terminal"] = time.monotonic()
            self.marks["pcm_buffer_high_water"] = stream.high_water
            operation.result = result
            self._diagnostic("presentation_terminal", tx_id=tx, status=result.state,
                adapter_failure_code=result.failure.value if result.failure else None,
                **(stream_failure(first_abort, "PRESENTATION") if first_abort else {}),
                stream_abort_reason=first_abort if first_abort in {"srs_collision_or_unexpected_origin", "physical_evidence_unavailable",
                    "stream_backpressure_timeout", "stream_tx_failed", "stream_cancelled", "radio_deadline"} else None,
                producer_done=producer is None or producer.done(), pcm_buffer_high_water=stream.high_water)
        return result

    async def cancel(self, tx: str) -> PresentationResult:
        if tx in self._streams:
            self._streams[tx].abort()
        return await super().cancel(tx)
