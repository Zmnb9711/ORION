"""Bounded protected-only coordinator; borrowed radio ownership is unchanged."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Callable, Protocol
from uuid import UUID

from orion.communication_contracts import (
    CommunicationProfileId,
    FinalizedCommunicationText,
    ResponseCompositionPlan,
)
from orion.radio_contracts import (
    FinalizedPcmAudio,
    RadioContext,
    RadioFailureCode,
    RadioTransmissionRequest,
    RadioTransmissionSnapshot,
    RadioTransmissionState,
)
from orion.radio_router import RadioRouter
from orion.response_composer import ResponseComposer
from orion.speechkit_tts_adapter import (
    SpeechKitAttemptObserver,
    TtsAdapterError,
    TtsFailureCode,
    normalize_speechkit_pcm,
    validate_pcm48,
)


class PresentationFailure(StrEnum):
    INVALID_FINALIZED_TEXT = "invalid_finalized_text"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    UNSUPPORTED_MIXED_OUTPUT = "unsupported_mixed_output"
    TTS_UNAVAILABLE = "tts_unavailable"
    TTS_TIMEOUT = "tts_timeout"
    TTS_REJECTED = "tts_rejected"
    TTS_ERROR = "tts_error"
    INVALID_PCM = "invalid_pcm"
    RADIO_CONTEXT_UNAVAILABLE = "radio_context_unavailable"
    RADIO_CONTEXT_MISMATCH = "radio_context_mismatch"
    RADIO_NOT_READY = "radio_not_ready"
    RADIO_REJECTED = "radio_rejected"
    RADIO_TIMEOUT = "radio_timeout"
    RADIO_ERROR = "radio_error"
    CANCELLED = "cancelled"
    SHUTTING_DOWN = "shutting_down"
    CONFLICTING_REPLAY = "conflicting_replay"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    CANCELLATION_UNSUPPORTED = "cancellation_unsupported"


@dataclass(frozen=True, slots=True)
class PresentationResult:
    tx_id: str
    state: str
    terminal: bool
    failure: PresentationFailure | None = None


class TtsPort(Protocol):
    async def synthesize(
        self,
        text: str,
        language: str,
        tx_id: str,
        observer: SpeechKitAttemptObserver | None = None,
    ) -> bytes: ...
    async def aclose(self) -> None: ...


@dataclass(slots=True)
class _Operation:
    signature: str
    task: asyncio.Task[PresentationResult] | None = None
    accepted: bool = False
    result: PresentationResult | None = None


def tx_correlation(interaction_id: UUID) -> str:
    return f"p7c-{interaction_id.hex}"


def _failure(tx: str, code: PresentationFailure) -> PresentationResult:
    return PresentationResult(tx, "failed", True, code)


def _radio_failure(code: RadioFailureCode) -> PresentationFailure:
    return {
        RadioFailureCode.NOT_READY: PresentationFailure.RADIO_NOT_READY,
        RadioFailureCode.TRANSPORT_UNAVAILABLE: PresentationFailure.RADIO_NOT_READY,
        RadioFailureCode.TX_TIMEOUT: PresentationFailure.RADIO_TIMEOUT,
        RadioFailureCode.TX_CANCELLED: PresentationFailure.CANCELLED,
        RadioFailureCode.TX_REJECTED: PresentationFailure.RADIO_REJECTED,
        RadioFailureCode.INVALID_CONTEXT: PresentationFailure.RADIO_CONTEXT_MISMATCH,
        RadioFailureCode.RADIO_UNAVAILABLE: PresentationFailure.RADIO_CONTEXT_UNAVAILABLE,
    }.get(code, PresentationFailure.RADIO_ERROR)


class ProtectedPresentationService:
    """One event-loop owner; at most 64 lifetime identities, no eviction/replay reset."""

    def __init__(
        self,
        tts: TtsPort,
        router: RadioRouter,
        *,
        transport_id: str,
        radio_timeout_s: float = 45.0,
        capacity: int = 64,
        normalize: Callable[[bytes], bytes] = normalize_speechkit_pcm,
    ) -> None:
        if not 0 < radio_timeout_s <= 45 or not 1 <= capacity <= 64:
            raise ValueError("Invalid presentation bounds")
        self._tts, self._router = tts, router
        self._transport = transport_id
        self._radio_timeout = radio_timeout_s
        self._capacity = capacity
        self._normalize = normalize
        self._operations: dict[str, _Operation] = {}
        self._events: deque[dict[str, object]] = deque(maxlen=1024)
        self._closing = False

    def diagnostics(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(event) for event in self._events)

    def _emit(self, event: str, tx: str, **fields: object) -> None:
        if event not in {
            "presentation_started",
            "tts_started",
            "tts_completed",
            "radio_submit_started",
            "radio_submit_completed",
            "presentation_completed",
            "presentation_failed",
            "speechkit_attempt_started",
            "speechkit_attempt_succeeded",
            "speechkit_attempt_failed",
            "speechkit_attempt_cancelled",
            "speechkit_retry_cancelled",
        }:
            return
        allowed = {
            "attempt_number",
            "elapsed_ms",
            "pcm_bytes",
            "status",
            "failure_code",
        }
        safe = {
            key: value
            for key, value in fields.items()
            if key in allowed
            and (
                value is None
                or isinstance(value, (int, float, bool))
                or key in {"status", "failure_code"}
                and isinstance(value, str)
            )
        }
        self._events.append({"event": event, "tx_id": tx, **safe})

    async def present(
        self, finalized: FinalizedCommunicationText, radio: RadioContext
    ) -> PresentationResult:
        tx = "invalid"
        try:
            raw = finalized.model_dump(mode="python", warnings="error")
            checked = FinalizedCommunicationText.model_validate(raw, strict=True)
            if checked.model_dump(mode="python") != raw:
                raise ValueError
            tx = tx_correlation(checked.interaction_id)
            if checked.envelope is not None:
                return _failure(tx, PresentationFailure.UNSUPPORTED_MIXED_OUTPUT)
            if checked.context.operational_language != "en-US":
                return _failure(tx, PresentationFailure.UNSUPPORTED_LANGUAGE)
            if (
                len(checked.protected_fragments) != 1
                or checked.context.profile_id != CommunicationProfileId.ICAO
            ):
                raise ValueError
            # Reuse Stage 7B policy for ingress checks, never use a rewritten result.
            recomposed = ResponseComposer().compose(
                ResponseCompositionPlan(
                    interaction_id=checked.interaction_id,
                    communication=checked.context,
                    priority=checked.priority,
                    protected_fragments=checked.protected_fragments,
                    suppress_conversational_envelope=checked.suppress_conversational_envelope,
                )
            )
            if recomposed != checked:
                raise ValueError
        except Exception:
            return _failure(tx, PresentationFailure.INVALID_FINALIZED_TEXT)
        try:
            raw_radio = radio.model_dump(mode="python", warnings="error")
            context = RadioContext.model_validate(raw_radio, strict=True)
            if context.model_dump(mode="python") != raw_radio:
                raise ValueError
        except Exception:
            return _failure(tx, PresentationFailure.RADIO_CONTEXT_UNAVAILABLE)
        if (
            context.tx_correlation_id != tx
            or context.source_domain != checked.context.domain
            or context.communication_priority != checked.priority
            or context.interaction_id not in (None, checked.interaction_id)
        ):
            return _failure(tx, PresentationFailure.RADIO_CONTEXT_MISMATCH)
        sources = list(context.provenance)
        for provenance in checked.provenance:
            if provenance.source not in sources:
                sources.append(provenance.source)
        try:
            context = RadioContext.model_validate(
                {
                    **context.model_dump(),
                    "interaction_id": checked.interaction_id,
                    "provenance": tuple(sources),
                }
            )
        except ValueError:
            return _failure(tx, PresentationFailure.RADIO_CONTEXT_MISMATCH)
        signature = hashlib.sha256(
            json.dumps(
                {
                    "finalized": checked.model_dump(mode="json"),
                    "radio": context.model_dump(mode="json"),
                },
                sort_keys=True,
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        existing = self._operations.get(tx)
        if existing is not None:
            if existing.signature != signature:
                return _failure(tx, PresentationFailure.CONFLICTING_REPLAY)
            if existing.task is not None and not existing.task.done():
                return await asyncio.shield(existing.task)
            return self.get(tx) or _failure(tx, PresentationFailure.RADIO_ERROR)
        if self._closing:
            return _failure(tx, PresentationFailure.SHUTTING_DOWN)
        if len(self._operations) >= self._capacity:
            return _failure(tx, PresentationFailure.CAPACITY_EXCEEDED)
        operation = _Operation(signature)
        self._operations[tx] = operation
        operation.task = asyncio.create_task(self._run(checked, context, operation))
        try:
            return await asyncio.shield(operation.task)
        except asyncio.CancelledError:
            await self.cancel(tx)
            raise

    def get(self, tx: str) -> PresentationResult | None:
        operation = self._operations.get(tx)
        if operation is None:
            return None
        if operation.accepted:
            try:
                snapshot = self._router.get(tx)
                operation.result = (
                    self._snapshot(snapshot)
                    if snapshot is not None
                    else PresentationResult(
                        tx, "unknown", False, PresentationFailure.RADIO_ERROR
                    )
                )
            except Exception:
                operation.result = PresentationResult(
                    tx, "unknown", False, PresentationFailure.RADIO_ERROR
                )
        return operation.result

    def _snapshot(self, snapshot: RadioTransmissionSnapshot) -> PresentationResult:
        terminal = snapshot.state in {
            RadioTransmissionState.COMPLETED,
            RadioTransmissionState.FAILED,
            RadioTransmissionState.CANCELLED,
        }
        code = (
            _radio_failure(snapshot.failure.code)
            if snapshot.failure
            else (None if terminal else PresentationFailure.RADIO_TIMEOUT)
        )
        return PresentationResult(
            str(snapshot.tx_correlation_id), snapshot.state.value, terminal, code
        )

    async def _run(
        self,
        finalized: FinalizedCommunicationText,
        context: RadioContext,
        operation: _Operation,
    ) -> PresentationResult:
        tx = str(context.tx_correlation_id)
        self._emit("presentation_started", tx)
        result = _failure(tx, PresentationFailure.TTS_ERROR)
        try:
            language = finalized.context.operational_language
            assert language == "en-US"  # Already checked before operation creation.
            self._emit("tts_started", tx)
            pcm48 = await self._tts.synthesize(
                finalized.text,
                language,
                tx,
                lambda event, fields: self._emit(
                    event,
                    tx,
                    **{
                        k: v
                        for k, v in fields.items()
                        if k in {"attempt_number", "elapsed_ms", "pcm_bytes"}
                    },
                ),
            )
            validate_pcm48(pcm48)
            try:
                pcm = FinalizedPcmAudio(
                    pcm=self._normalize(pcm48), sample_rate_hz=44100
                )
            except Exception:
                raise TtsAdapterError(TtsFailureCode.INVALID_PCM) from None
            self._emit("tts_completed", tx, pcm_bytes=len(pcm.pcm))
            # Explicit scheduling point before atomic admission/cancellation decision.
            await asyncio.sleep(0)
            if self._closing:
                raise asyncio.CancelledError
            request = RadioTransmissionRequest(
                context=context,
                audio=pcm,
                transport_id=self._transport,
                timeout_s=self._radio_timeout,
            )
            self._emit("radio_submit_started", tx)
            # A throwing submit may already have side effects: never replay it.
            operation.accepted = True
            submitted = self._router.submit(request)
            operation.accepted = submitted.accepted
            self._emit(
                "radio_submit_completed",
                tx,
                status="accepted" if submitted.accepted else "rejected",
            )
            if not submitted.accepted:
                result = _failure(
                    tx,
                    _radio_failure(submitted.failure.code)
                    if submitted.failure
                    else PresentationFailure.RADIO_ERROR,
                )
            else:
                deadline = asyncio.get_running_loop().time() + self._radio_timeout
                while True:
                    snapshot = self._router.get(tx)
                    if snapshot is None:
                        result = PresentationResult(
                            tx, "unknown", False, PresentationFailure.RADIO_ERROR
                        )
                        break
                    result = self._snapshot(snapshot)
                    if result.terminal or asyncio.get_running_loop().time() >= deadline:
                        break
                    await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            result = (
                self.get(tx)
                if operation.accepted
                else PresentationResult(
                    tx, "cancelled", True, PresentationFailure.CANCELLED
                )
            )
            if result is None:
                result = PresentationResult(
                    tx, "active", False, PresentationFailure.RADIO_TIMEOUT
                )
        except TtsAdapterError as exc:
            result = _failure(tx, PresentationFailure(exc.code.value))
        except Exception:
            result = (
                PresentationResult(
                    tx, "unknown", False, PresentationFailure.RADIO_ERROR
                )
                if operation.accepted
                else _failure(tx, PresentationFailure.TTS_ERROR)
            )
        finally:
            operation.result = result
        self._emit(
            "presentation_completed"
            if result.state == "completed"
            else "presentation_failed",
            tx,
            status=result.state,
            failure_code=result.failure.value if result.failure else None,
        )
        return result

    async def cancel(self, tx: str) -> PresentationResult:
        operation = self._operations.get(tx)
        if operation is None:
            return _failure("invalid", PresentationFailure.INVALID_FINALIZED_TEXT)
        if operation.accepted:
            try:
                cancelled = self._router.cancel(tx)
            except Exception:
                return PresentationResult(
                    tx, "unknown", False, PresentationFailure.RADIO_ERROR
                )
            result = self.get(tx)
            if result is None:
                return PresentationResult(
                    tx, "unknown", False, PresentationFailure.RADIO_ERROR
                )
            if not cancelled.cancelled and not result.terminal:
                return PresentationResult(
                    tx,
                    result.state,
                    False,
                    PresentationFailure.CANCELLATION_UNSUPPORTED,
                )
            return result
        if operation.task is not None and not operation.task.done():
            operation.task.cancel()
            try:
                return await operation.task
            except asyncio.CancelledError:
                operation.result = PresentationResult(
                    tx, "cancelled", True, PresentationFailure.CANCELLED
                )
        return operation.result or _failure(tx, PresentationFailure.CANCELLED)

    async def shutdown(self, timeout_s: float = 2.0) -> bool:
        if not 0 < timeout_s <= 5:
            raise ValueError("Invalid shutdown bound")
        self._closing = True
        tasks = []
        for operation in self._operations.values():
            if operation.task is not None and not operation.task.done():
                operation.task.cancel()  # Stops own waiting/TTS, never the borrowed radio.
                tasks.append(operation.task)
        try:
            async with asyncio.timeout(timeout_s):
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await self._tts.aclose()
            for tx, operation in self._operations.items():
                if operation.accepted:
                    result = self.get(tx)
                    if result is None or not result.terminal:
                        return False
                elif operation.result is None:
                    operation.result = PresentationResult(
                        tx, "cancelled", True, PresentationFailure.CANCELLED
                    )
            return True
        except Exception:
            return False
