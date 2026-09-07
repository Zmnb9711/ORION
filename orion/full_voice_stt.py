"""Native External-EOU barrier for one controlled physical radio turn.

No transcript merging, VAD, semantic interpretation, provider retry, or output.
All methods and the receiver run on the same asyncio loop. The owner releases
the turn only after its downstream terminal result (half-duplex, no turn queue).
"""

from __future__ import annotations

import asyncio
from array import array
from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
import sys
from math import sqrt
from typing import Callable
from uuid import UUID

from orion.speechkit_v3_stt_transport import (
    SpeechKitProviderEvent,
    SpeechKitStreamingPort,
    SpeechKitSttProtocolError,
)


@dataclass(frozen=True, slots=True)
class FinalizedUserUtterance:
    interaction_id: UUID
    text: str = field(repr=False)
    physical_start: float
    physical_end: float
    last_pcm: float
    eou_sent: float
    final_received: float
    barrier_closed: float
    started_at: datetime
    finalized_at: datetime
    provider_session: str = field(repr=False)
    final_index: int
    pcm_bytes: int
    input_language: str = "ru-RU"


class NativeSpeechKitTurns:
    """Bounded persistent RPC; FINAL and EOU_UPDATE must identify one barrier."""

    def __init__(
        self,
        port: SpeechKitStreamingPort,
        *,
        fail: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
        barrier_timeout: float = 5.0,
        max_audio_bytes: int = 960_000,
    ) -> None:
        self.port = port
        self.fail = fail
        self.clock = clock
        self.barrier_timeout = barrier_timeout
        self.max_audio_bytes = max_audio_bytes
        self.owner: UUID | None = None
        self.future: asyncio.Future[FinalizedUserUtterance | None] | None = None
        self._reader: asyncio.Task[None] | None = None
        self._timer: asyncio.Task[None] | None = None
        self._closed = False
        self._failed = False
        self._pending = False
        self._sealed = False
        self._session: str | None = None
        self._last_index = -1
        self._terminal: dict[str, SpeechKitProviderEvent] = {}
        self._marks: dict[str, float] = {}
        self._bytes = 0
        self._events = 0
        self._samples = self._nonzero = self._peak = self._squares = 0
        self._partial_events = self._partial_characters_max = 0
        self._started_at = datetime.now(UTC)

    async def open(self, api_key: str) -> None:
        if self._reader is not None or self._closed:
            raise SpeechKitSttProtocolError("invalid_session_state")
        try:
            await asyncio.wait_for(self.port.open(api_key), 10.0)
            self._reader = asyncio.create_task(self._receive(), name="full-voice-stt")
        except BaseException:
            await self.close()
            raise

    def start(self, identity: UUID, physical_start: float) -> None:
        if self.owner is not None or self._closed or self._failed or not self._reader:
            self._reject("turn_busy_or_unavailable")
        self.owner = identity
        self._pending = self._sealed = False
        self._terminal = {}
        self._marks = {"physical_start": physical_start}
        self._bytes = self._events = 0
        self._samples = self._nonzero = self._peak = self._squares = 0
        self._partial_events = self._partial_characters_max = 0
        self._started_at = datetime.now(UTC)
        self.future = asyncio.get_running_loop().create_future()

    async def audio(self, identity: UUID, pcm: bytes, received_at: float) -> None:
        if identity != self.owner or self._pending or self._sealed or self._failed:
            self._reject("pcm_turn_mismatch")
        if not pcm or len(pcm) % 2 or self._bytes + len(pcm) > self.max_audio_bytes:
            self._reject("invalid_or_excessive_pcm")
        self._bytes += len(pcm)
        # Aggregate only; no audio or transcript persistence. This distinguishes
        # a valid empty ASR result from zero/very quiet incoming radio PCM.
        samples = array("h", pcm)
        if sys.byteorder != "little":
            samples.byteswap()
        self._samples += len(samples)
        self._nonzero += sum(value != 0 for value in samples)
        self._peak = max(self._peak, max(abs(value) for value in samples))
        self._squares += sum(value * value for value in samples)
        self._marks["last_pcm"] = received_at
        try:
            await asyncio.wait_for(self.port.send_audio(pcm), 2.0)
        except Exception:
            self._reject("stt_audio_transport_failed")

    async def end(self, identity: UUID, physical_end: float) -> None:
        if identity != self.owner or self._pending or self._sealed or self._failed:
            self._reject("eou_turn_mismatch")
        if not self._bytes:
            self._reject("empty_physical_turn")
        self._marks["physical_end"] = physical_end
        self._pending = True
        self._marks["eou_sent"] = self.clock()
        try:
            await asyncio.wait_for(self.port.send_eou(), 2.0)
        except Exception:
            self._reject("stt_eou_transport_failed")
        if not self._sealed:
            self._timer = asyncio.create_task(self._deadline())

    async def result(self) -> FinalizedUserUtterance | None:
        if self.future is None:
            raise SpeechKitSttProtocolError("no_turn")
        return await asyncio.shield(self.future)

    def release(self, identity: UUID) -> None:
        if identity != self.owner or not self._sealed or self._failed:
            self._reject("invalid_turn_release")
        self.owner = None
        # Retain terminal identities until the next start, to reject late conflict.

    def accept(self, event: SpeechKitProviderEvent) -> None:
        """Native provider events only; partials can never dispatch an utterance."""
        if self._closed or self._failed:
            return
        self._events += 1
        if self._events > 2048:
            self._reject("provider_event_bound")
        if event.kind == "status_code":
            if event.status not in {"OK", "WORKING"}:
                self._reject("provider_status_failure")
            return
        if event.kind not in {"final", "eou_update"}:
            if event.kind == "partial":
                self._partial_events += 1
                self._partial_characters_max = max(self._partial_characters_max, len(event.transcript))
            return
        old = self._terminal.get(event.kind)
        if old is not None:
            if old == event:
                return
            self._reject("conflicting_terminal_event")
        if self.owner is None or not self._pending or self._sealed:
            self._reject("terminal_without_physical_end")
        if not event.session_uuid or event.final_index <= self._last_index:
            self._reject("terminal_identity_invalid")
        if self._session is not None and event.session_uuid != self._session:
            self._reject("provider_session_changed")
        self._session = event.session_uuid
        if event.kind == "final":
            if len(event.transcript) > 4000:
                self._reject("transcript_bound")
            self._marks["final_received"] = self.clock()
        self._terminal[event.kind] = event
        if set(self._terminal) != {"final", "eou_update"}:
            return
        final, eou = self._terminal["final"], self._terminal["eou_update"]
        if not (
            final.final_index == eou.final_index
            and final.session_uuid == eou.session_uuid
            and final.received_data_ms == final.final_time_ms
            and final.received_data_ms == eou.received_data_ms
            and eou.received_data_ms == eou.final_time_ms == eou.eou_time_ms
            and eou.eou_time_ms > 0
        ):
            self._reject("invalid_final_eou_barrier")
        self._sealed = True
        self._last_index = final.final_index
        if self._timer:
            self._timer.cancel()
        result = None
        if final.transcript and not final.transcript.isspace():
            assert self.owner is not None
            result = FinalizedUserUtterance(
                interaction_id=self.owner,
                text=final.transcript,
                physical_start=self._marks["physical_start"],
                physical_end=self._marks["physical_end"],
                last_pcm=self._marks["last_pcm"],
                eou_sent=self._marks["eou_sent"],
                final_received=self._marks["final_received"],
                barrier_closed=self.clock(),
                started_at=self._started_at,
                finalized_at=datetime.now(UTC),
                provider_session=final.session_uuid,
                final_index=final.final_index,
                pcm_bytes=self._bytes,
            )
        assert self.future is not None
        self.future.set_result(result)

    def safe_turn_evidence(self) -> dict[str, object]:
        """Bounded scalar-only evidence survives empty FINAL and contains no text."""
        final = self._terminal.get("final")
        eou = self._terminal.get("eou_update")
        return {
            "pcm_bytes": self._bytes,
            "pcm_sample_rate_hz": 16000,
            "pcm_duration_ms": self._bytes / 32,
            "pcm_peak_abs": self._peak,
            "pcm_rms": round(sqrt(self._squares / self._samples), 3) if self._samples else 0.0,
            "pcm_nonzero_samples": self._nonzero,
            "partial_events": self._partial_events,
            "partial_characters_max": self._partial_characters_max,
            "final_characters": len(final.transcript) if final is not None else None,
            "provider_final_index": final.final_index if final is not None else None,
            "provider_received_ms": final.received_data_ms if final is not None else None,
            "provider_eou_ms": eou.eou_time_ms if eou is not None else None,
            "final_eou_barrier_closed": self._sealed,
            "input_marks": dict(self._marks),
        }

    def _reject(self, code: str) -> None:
        self._failed = True
        if self.future is not None and not self.future.done():
            self.future.cancel()
        self.fail(code)
        raise SpeechKitSttProtocolError(code)

    async def _deadline(self) -> None:
        await asyncio.sleep(self.barrier_timeout)
        try:
            self._reject("final_eou_timeout")
        except SpeechKitSttProtocolError:
            pass

    async def _receive(self) -> None:
        try:
            while not self._closed:
                event = await self.port.receive()
                if event is None:
                    self._reject("unexpected_provider_eof")
                assert event is not None
                self.accept(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._failed and not self._closed:
                try:
                    self._reject("provider_transport_failure")
                except SpeechKitSttProtocolError:
                    pass

    async def close(self) -> None:
        self._closed = True
        if self.future is not None and not self.future.done():
            self.future.cancel()
        tasks = [task for task in (self._reader, self._timer) if task is not None]
        for task in tasks:
            task.cancel()
        try:
            await asyncio.wait_for(self.port.close(), 2.0)
        finally:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
