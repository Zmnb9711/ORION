"""Core-owned bounded semantic transmission router for Stage 6B.1."""

from __future__ import annotations

import hashlib
import heapq
import json
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from orion.communication_contracts import CommunicationPriority
from orion.radio_contracts import (
    REQUIRED_TX_CAPABILITIES,
    RadioAdapterOutcome,
    RadioAdapterTxResult,
    RadioCancellationResult,
    RadioDiagnosticEvent,
    RadioDiagnosticStage,
    RadioFailure,
    RadioFailureCode,
    RadioReadiness,
    RadioRouterShutdownResult,
    RadioSubmissionResult,
    RadioTransmissionRequest,
    RadioTransmissionSnapshot,
    RadioTransmissionState,
    RadioTransportAdapter,
    RadioTransportCapability,
    RadioTransportStatus,
    TransportId,
)


DEFAULT_QUEUE_CAPACITY = 8
DEFAULT_MAX_ADAPTERS = 8
DEFAULT_REPLAY_CAPACITY = 256
DEFAULT_DIAGNOSTIC_CAPACITY = 500

_PRIORITY_ORDER = {
    CommunicationPriority.ROUTINE: 0,
    CommunicationPriority.IMPORTANT: 1,
    CommunicationPriority.URGENT: 2,
    CommunicationPriority.IMMEDIATE: 3,
}
_TERMINAL_STATES = {
    RadioTransmissionState.COMPLETED,
    RadioTransmissionState.FAILED,
    RadioTransmissionState.CANCELLED,
}


@dataclass(slots=True)
class _TransmissionRecord:
    request: RadioTransmissionRequest | None
    signature: str
    snapshot: RadioTransmissionSnapshot
    done: threading.Event = field(default_factory=threading.Event)


class RadioRouter:
    """Select one adapter and serialize finalized audio under Core policy."""

    def __init__(
        self,
        *,
        default_transport_id: TransportId | None = None,
        queue_capacity: int = DEFAULT_QUEUE_CAPACITY,
        max_adapters: int = DEFAULT_MAX_ADAPTERS,
        max_replay_entries: int = DEFAULT_REPLAY_CAPACITY,
        max_diagnostics: int = DEFAULT_DIAGNOSTIC_CAPACITY,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if queue_capacity <= 0:
            raise ValueError("Radio queue capacity must be positive")
        if max_adapters <= 0:
            raise ValueError("Radio adapter registry bound must be positive")
        if max_replay_entries <= queue_capacity:
            raise ValueError("Radio replay capacity must exceed queue capacity")
        if max_diagnostics <= 0:
            raise ValueError("Radio diagnostic capacity must be positive")
        self._default_transport_id = default_transport_id
        self._queue_capacity = queue_capacity
        self._max_adapters = max_adapters
        self._max_replay_entries = max_replay_entries
        self._clock = clock
        self._monotonic = monotonic
        self._adapters: dict[str, RadioTransportAdapter] = {}
        self._adapter_start_failures: set[str] = set()
        self._records: OrderedDict[str, _TransmissionRecord] = OrderedDict()
        self._queue: list[tuple[int, int, str]] = []
        self._queued_ids: set[str] = set()
        self._sequence = 0
        self._active_id: str | None = None
        self._diagnostics: deque[RadioDiagnosticEvent] = deque(maxlen=max_diagnostics)
        self._condition = threading.Condition(threading.RLock())
        self._worker: threading.Thread | None = None
        self._started = False
        self._accepting = False
        self._stop_requested = False
        self._shutdown_result: RadioRouterShutdownResult | None = None

    def register_adapter(self, adapter: RadioTransportAdapter) -> RadioTransportStatus:
        """Register one explicit adapter without making it a silent fallback."""

        status = adapter.status()
        transport_id = str(status.transport_id)
        if adapter.transport_id != transport_id:
            raise ValueError("Radio adapter identity does not match its status")
        capabilities = adapter.capabilities()
        if not isinstance(capabilities, frozenset) or any(
            not isinstance(item, RadioTransportCapability) for item in capabilities
        ):
            raise ValueError("Radio adapter capabilities must be a typed frozenset")
        with self._condition:
            if self._started or self._shutdown_result is not None:
                raise RuntimeError(
                    "Radio adapters must be registered before Router start"
                )
            if transport_id in self._adapters:
                raise ValueError(
                    f"Radio transport {transport_id!r} is already registered"
                )
            if len(self._adapters) >= self._max_adapters:
                raise ValueError("Radio adapter registry reached its hard bound")
            self._adapters[transport_id] = adapter
        return status

    def start(self) -> tuple[RadioTransportStatus, ...]:
        """Start registered adapters and the single semantic queue worker."""

        with self._condition:
            if self._shutdown_result is not None:
                raise RuntimeError("Stopped RadioRouter cannot be restarted")
            if self._started:
                return tuple(adapter.status() for adapter in self._adapters.values())
            adapters = tuple(self._adapters.values())
        statuses: list[RadioTransportStatus] = []
        for adapter in adapters:
            try:
                status = adapter.start()
                if status.transport_id != adapter.transport_id:
                    raise ValueError(
                        "Radio adapter start returned inconsistent identity"
                    )
                statuses.append(status)
            except Exception:
                self._adapter_start_failures.add(adapter.transport_id)
                statuses.append(
                    RadioTransportStatus(
                        transport_id=adapter.transport_id,
                        readiness=RadioReadiness.ERROR,
                        detail="Radio transport failed during start",
                    )
                )
        with self._condition:
            self._started = True
            self._accepting = True
            self._worker = threading.Thread(
                target=self._run,
                name="orion-radio-router",
                daemon=True,
            )
            self._worker.start()
        return tuple(statuses)

    def submit(self, request: RadioTransmissionRequest) -> RadioSubmissionResult:
        """Validate, deduplicate and enqueue one finalized PCM transmission."""

        signature = _request_signature(request)
        tx_id = str(request.context.tx_correlation_id)
        with self._condition:
            replay = self._records.get(tx_id)
            if replay is not None:
                self._records.move_to_end(tx_id)
                if replay.signature == signature:
                    self._record(replay.snapshot, RadioDiagnosticStage.REPLAYED)
                    return RadioSubmissionResult(
                        accepted=True,
                        replayed=True,
                        transmission=replay.snapshot,
                    )
                return self._reject(
                    request,
                    RadioFailureCode.INVALID_CONTEXT,
                    "Radio correlation ID was reused with different content",
                    request.transport_id or self._default_transport_id,
                )
            if not self._started or not self._accepting:
                return self._reject(
                    request,
                    RadioFailureCode.NOT_READY,
                    "RadioRouter is not accepting transmissions",
                    request.transport_id or self._default_transport_id,
                )
            transport_id = request.transport_id or self._default_transport_id
            adapter, failure = self._resolve_adapter(request, transport_id)
            if adapter is None:
                assert failure is not None
                return self._reject_with_failure(request, failure, transport_id)
            if len(self._queued_ids) >= self._queue_capacity:
                return self._reject(
                    request,
                    RadioFailureCode.TX_REJECTED,
                    "Radio transmission queue is full",
                    transport_id,
                )
            now = self._now()
            snapshot = RadioTransmissionSnapshot(
                tx_correlation_id=request.context.tx_correlation_id,
                transport_id=adapter.transport_id,
                state=RadioTransmissionState.QUEUED,
                source_domain=request.context.source_domain,
                radio_entity_id=request.context.radio_entity.entity_id,
                priority=request.context.communication_priority,
                target_frequency_hz=request.context.target_frequency_hz,
                modulation=request.context.modulation,
                enqueued_at=now,
            )
            record = _TransmissionRecord(request, signature, snapshot)
            self._records[tx_id] = record
            self._queued_ids.add(tx_id)
            self._sequence += 1
            heapq.heappush(
                self._queue,
                (
                    -_PRIORITY_ORDER[request.context.communication_priority],
                    self._sequence,
                    tx_id,
                ),
            )
            self._trim_replay_locked()
            self._record(snapshot, RadioDiagnosticStage.ENQUEUED)
            self._condition.notify()
            return RadioSubmissionResult(accepted=True, transmission=snapshot)

    def get(self, tx_correlation_id: str) -> RadioTransmissionSnapshot | None:
        with self._condition:
            record = self._records.get(tx_correlation_id)
            return record.snapshot if record is not None else None

    def wait(
        self,
        tx_correlation_id: str,
        timeout_s: float | None = None,
    ) -> RadioTransmissionSnapshot | None:
        if timeout_s is not None and timeout_s < 0:
            raise ValueError("Radio wait timeout must not be negative")
        with self._condition:
            record = self._records.get(tx_correlation_id)
        if record is None:
            return None
        record.done.wait(timeout_s)
        with self._condition:
            return record.snapshot

    def cancel(self, tx_correlation_id: str) -> RadioCancellationResult:
        """Cancel queued work or explicitly delegate supported active cancellation."""

        with self._condition:
            record = self._records.get(tx_correlation_id)
            if record is None:
                return RadioCancellationResult(
                    tx_correlation_id=tx_correlation_id,
                    cancelled=False,
                    failure=_failure(
                        RadioFailureCode.INVALID_CONTEXT,
                        "Unknown radio transmission correlation ID",
                    ),
                )
            snapshot = record.snapshot
            if snapshot.state is RadioTransmissionState.QUEUED:
                self._queued_ids.discard(tx_correlation_id)
                failure = _failure(
                    RadioFailureCode.TX_CANCELLED,
                    "Queued radio transmission was cancelled",
                    snapshot.transport_id,
                )
                cancelled = snapshot.model_copy(
                    update={
                        "state": RadioTransmissionState.CANCELLED,
                        "completed_at": self._now(),
                        "failure": failure,
                    }
                )
                record.snapshot = cancelled
                record.request = None
                record.done.set()
                self._record(cancelled, RadioDiagnosticStage.CANCELLED)
                self._condition.notify_all()
                return RadioCancellationResult(
                    tx_correlation_id=tx_correlation_id,
                    cancelled=True,
                    state=RadioTransmissionState.CANCELLED,
                )
            if snapshot.state in _TERMINAL_STATES:
                return RadioCancellationResult(
                    tx_correlation_id=tx_correlation_id,
                    cancelled=False,
                    state=snapshot.state,
                    failure=_failure(
                        RadioFailureCode.TX_REJECTED,
                        "Radio transmission is already terminal",
                        snapshot.transport_id,
                    ),
                )
            adapter = self._adapters[snapshot.transport_id]
            try:
                can_cancel = (
                    RadioTransportCapability.TRANSMISSION_CANCEL
                    in adapter.capabilities()
                )
            except Exception:
                return RadioCancellationResult(
                    tx_correlation_id=tx_correlation_id,
                    cancelled=False,
                    state=RadioTransmissionState.ACTIVE,
                    failure=_failure(
                        RadioFailureCode.TRANSPORT_ERROR,
                        "Radio transport capabilities could not be read",
                        snapshot.transport_id,
                    ),
                )
            if not can_cancel:
                return RadioCancellationResult(
                    tx_correlation_id=tx_correlation_id,
                    cancelled=False,
                    state=RadioTransmissionState.ACTIVE,
                    failure=_failure(
                        RadioFailureCode.UNSUPPORTED_CAPABILITY,
                        "Active radio transmission cancellation is unsupported",
                        snapshot.transport_id,
                    ),
                )
        try:
            accepted = adapter.cancel(tx_correlation_id)
        except Exception:
            accepted = False
        if not accepted:
            return RadioCancellationResult(
                tx_correlation_id=tx_correlation_id,
                cancelled=False,
                state=RadioTransmissionState.ACTIVE,
                failure=_failure(
                    RadioFailureCode.TX_REJECTED,
                    "Radio transport rejected active cancellation",
                    snapshot.transport_id,
                ),
            )
        return RadioCancellationResult(
            tx_correlation_id=tx_correlation_id,
            cancelled=True,
            state=RadioTransmissionState.ACTIVE,
        )

    def diagnostic_snapshot(self) -> tuple[RadioDiagnosticEvent, ...]:
        with self._condition:
            return tuple(self._diagnostics)

    def shutdown(self, timeout_s: float = 2.0) -> RadioRouterShutdownResult:
        """Stop admission, cancel queued work and close every adapter boundedly."""

        if timeout_s <= 0:
            raise ValueError("RadioRouter shutdown timeout must be positive")
        with self._condition:
            if self._shutdown_result is not None:
                return self._shutdown_result.model_copy(
                    update={"already_stopped": True}
                )
            self._accepting = False
            self._stop_requested = True
            queued_cancelled = 0
            for tx_id in tuple(self._queued_ids):
                record = self._records[tx_id]
                failure = _failure(
                    RadioFailureCode.TX_CANCELLED,
                    "Radio transmission was cancelled by Router shutdown",
                    record.snapshot.transport_id,
                )
                record.snapshot = record.snapshot.model_copy(
                    update={
                        "state": RadioTransmissionState.CANCELLED,
                        "completed_at": self._now(),
                        "failure": failure,
                    }
                )
                record.request = None
                record.done.set()
                self._record(record.snapshot, RadioDiagnosticStage.CANCELLED)
                queued_cancelled += 1
            self._queued_ids.clear()
            active_id = self._active_id
            adapters = tuple(self._adapters.values())
            worker = self._worker
            self._condition.notify_all()

        deadline = self._monotonic() + timeout_s
        if active_id is not None:
            active = self.get(active_id)
            if active is not None:
                adapter = self._adapters[active.transport_id]
                try:
                    can_cancel = (
                        RadioTransportCapability.TRANSMISSION_CANCEL
                        in adapter.capabilities()
                    )
                except Exception:
                    can_cancel = False
                if can_cancel:
                    try:
                        adapter.cancel(active_id)
                    except Exception:
                        pass

        adapters_stopped = 0
        adapter_failures = 0
        for adapter in adapters:
            remaining = max(0.001, deadline - self._monotonic())
            try:
                stopped = adapter.shutdown(remaining)
            except Exception:
                stopped = False
            if stopped:
                adapters_stopped += 1
            else:
                adapter_failures += 1
        if worker is not None and worker.is_alive():
            worker.join(max(0.0, deadline - self._monotonic()))
        worker_stopped = worker is None or not worker.is_alive()
        result = RadioRouterShutdownResult(
            clean=worker_stopped and adapter_failures == 0,
            queued_cancelled=queued_cancelled,
            adapters_stopped=adapters_stopped,
            adapter_shutdown_failures=adapter_failures,
            worker_stopped=worker_stopped,
        )
        with self._condition:
            self._started = False
            self._shutdown_result = result
        return result

    def _run(self) -> None:
        while True:
            with self._condition:
                record = self._next_record_locked()
                while record is None and not self._stop_requested:
                    self._condition.wait()
                    record = self._next_record_locked()
                if record is None and self._stop_requested:
                    return
                assert record is not None
                request = record.request
                assert request is not None
                tx_id = str(request.context.tx_correlation_id)
                transport_id = record.snapshot.transport_id
                adapter, failure = self._resolve_adapter(request, transport_id)
                if adapter is None:
                    assert failure is not None
                    self._terminal_failure_locked(record, failure)
                    continue
                active = record.snapshot.model_copy(
                    update={
                        "state": RadioTransmissionState.ACTIVE,
                        "started_at": self._now(),
                    }
                )
                record.snapshot = active
                self._active_id = tx_id
                self._record(active, RadioDiagnosticStage.STARTED)
            try:
                result = adapter.transmit(request)
            except Exception:
                result = RadioAdapterTxResult(
                    tx_correlation_id=request.context.tx_correlation_id,
                    outcome=RadioAdapterOutcome.FAILED,
                    started_at=record.snapshot.started_at,
                    completed_at=self._now(),
                    failure=_failure(
                        RadioFailureCode.TRANSPORT_ERROR,
                        "Radio transport failed during transmission",
                        transport_id,
                    ),
                )
            with self._condition:
                self._active_id = None
                self._apply_result_locked(record, result)
                self._condition.notify_all()

    def _next_record_locked(self) -> _TransmissionRecord | None:
        while self._queue:
            _priority, _sequence, tx_id = heapq.heappop(self._queue)
            if tx_id not in self._queued_ids:
                continue
            record = self._records.get(tx_id)
            if (
                record is None
                or record.snapshot.state is not RadioTransmissionState.QUEUED
            ):
                self._queued_ids.discard(tx_id)
                continue
            self._queued_ids.discard(tx_id)
            return record
        return None

    def _resolve_adapter(
        self,
        request: RadioTransmissionRequest,
        transport_id: str | None,
    ) -> tuple[RadioTransportAdapter | None, RadioFailure | None]:
        if transport_id is None:
            return None, _failure(
                RadioFailureCode.TRANSPORT_UNAVAILABLE,
                "No radio transport was requested or configured",
            )
        adapter = self._adapters.get(transport_id)
        if adapter is None:
            return None, _failure(
                RadioFailureCode.TRANSPORT_UNAVAILABLE,
                "Requested radio transport is unavailable",
                transport_id,
            )
        if transport_id in self._adapter_start_failures:
            return None, _failure(
                RadioFailureCode.NOT_READY,
                "Requested radio transport failed during start",
                transport_id,
            )
        try:
            capabilities = adapter.capabilities()
            missing = REQUIRED_TX_CAPABILITIES - capabilities
            status = adapter.status()
        except Exception:
            return None, _failure(
                RadioFailureCode.TRANSPORT_ERROR,
                "Radio transport status could not be read",
                transport_id,
            )
        if missing:
            return None, _failure(
                RadioFailureCode.UNSUPPORTED_CAPABILITY,
                "Radio transport lacks required transmission capabilities",
                transport_id,
            )
        if status.transport_id != transport_id:
            return None, _failure(
                RadioFailureCode.TRANSPORT_ERROR,
                "Radio transport returned inconsistent identity",
                transport_id,
            )
        if status.readiness is RadioReadiness.UNAVAILABLE:
            return None, _failure(
                RadioFailureCode.TRANSPORT_UNAVAILABLE,
                "Requested radio transport is unavailable",
                transport_id,
                retryable=True,
            )
        if status.readiness is not RadioReadiness.READY:
            return None, _failure(
                RadioFailureCode.NOT_READY,
                "Requested radio transport is not ready",
                transport_id,
                retryable=status.readiness
                in {RadioReadiness.STARTING, RadioReadiness.DEGRADED},
            )
        return adapter, None

    def _apply_result_locked(
        self,
        record: _TransmissionRecord,
        result: RadioAdapterTxResult,
    ) -> None:
        if record.snapshot.state in _TERMINAL_STATES:
            return
        if result.tx_correlation_id != record.snapshot.tx_correlation_id:
            self._terminal_failure_locked(
                record,
                _failure(
                    RadioFailureCode.TRANSPORT_ERROR,
                    "Radio transport returned mismatched correlation",
                    record.snapshot.transport_id,
                ),
            )
            return
        updates: dict[str, object] = {
            "started_at": result.started_at or record.snapshot.started_at,
            "completed_at": result.completed_at,
            "frame_count": result.frame_count,
            "duration_ms": result.duration_ms,
        }
        if result.outcome is RadioAdapterOutcome.COMPLETED:
            updates.update(state=RadioTransmissionState.COMPLETED, failure=None)
            stage = RadioDiagnosticStage.COMPLETED
        elif result.outcome is RadioAdapterOutcome.CANCELLED:
            updates.update(
                state=RadioTransmissionState.CANCELLED,
                failure=_failure(
                    RadioFailureCode.TX_CANCELLED,
                    "Active radio transmission was cancelled",
                    record.snapshot.transport_id,
                ),
            )
            stage = RadioDiagnosticStage.CANCELLED
        else:
            failure = result.failure or _failure(
                RadioFailureCode.TRANSPORT_ERROR,
                "Radio transport failed during transmission",
                record.snapshot.transport_id,
            )
            updates.update(
                state=RadioTransmissionState.FAILED,
                failure=_normalized_failure(failure, record.snapshot.transport_id),
            )
            stage = RadioDiagnosticStage.FAILED
        record.snapshot = record.snapshot.model_copy(update=updates)
        record.request = None
        record.done.set()
        self._record(record.snapshot, stage)
        self._trim_replay_locked()

    def _terminal_failure_locked(
        self,
        record: _TransmissionRecord,
        failure: RadioFailure,
    ) -> None:
        if record.snapshot.state in _TERMINAL_STATES:
            return
        record.snapshot = record.snapshot.model_copy(
            update={
                "state": RadioTransmissionState.FAILED,
                "completed_at": self._now(),
                "failure": _normalized_failure(failure, record.snapshot.transport_id),
            }
        )
        record.request = None
        record.done.set()
        self._record(record.snapshot, RadioDiagnosticStage.FAILED)

    def _reject(
        self,
        request: RadioTransmissionRequest,
        code: RadioFailureCode,
        message: str,
        transport_id: str | None,
    ) -> RadioSubmissionResult:
        return self._reject_with_failure(
            request,
            _failure(code, message, transport_id),
            transport_id,
        )

    def _reject_with_failure(
        self,
        request: RadioTransmissionRequest,
        failure: RadioFailure,
        transport_id: str | None,
    ) -> RadioSubmissionResult:
        self._record_request(
            request,
            RadioDiagnosticStage.REJECTED,
            transport_id or "unresolved",
            failure.code,
        )
        return RadioSubmissionResult(accepted=False, failure=failure)

    def _record(
        self,
        snapshot: RadioTransmissionSnapshot,
        stage: RadioDiagnosticStage,
    ) -> None:
        self._diagnostics.append(
            RadioDiagnosticEvent(
                stage=stage,
                timestamp=self._now(),
                transport_id=snapshot.transport_id,
                tx_correlation_id=snapshot.tx_correlation_id,
                source_domain=snapshot.source_domain,
                radio_entity_id=snapshot.radio_entity_id,
                priority=snapshot.priority,
                target_frequency_hz=snapshot.target_frequency_hz,
                modulation=snapshot.modulation,
                failure_code=snapshot.failure.code if snapshot.failure else None,
            )
        )

    def _record_request(
        self,
        request: RadioTransmissionRequest,
        stage: RadioDiagnosticStage,
        transport_id: str,
        failure_code: RadioFailureCode | None = None,
    ) -> None:
        context = request.context
        self._diagnostics.append(
            RadioDiagnosticEvent(
                stage=stage,
                timestamp=self._now(),
                transport_id=transport_id,
                tx_correlation_id=context.tx_correlation_id,
                source_domain=context.source_domain,
                radio_entity_id=context.radio_entity.entity_id,
                priority=context.communication_priority,
                target_frequency_hz=context.target_frequency_hz,
                modulation=context.modulation,
                failure_code=failure_code,
            )
        )

    def _trim_replay_locked(self) -> None:
        while len(self._records) > self._max_replay_entries:
            removable = next(
                (
                    key
                    for key, record in self._records.items()
                    if record.snapshot.state in _TERMINAL_STATES
                ),
                None,
            )
            if removable is None:
                return
            self._records.pop(removable)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("RadioRouter clock must return timezone-aware timestamps")
        return value


_GENERIC_FAILURE_MESSAGES = {
    RadioFailureCode.TRANSPORT_UNAVAILABLE: "Requested radio transport is unavailable",
    RadioFailureCode.NOT_READY: "Requested radio transport is not ready",
    RadioFailureCode.RADIO_UNAVAILABLE: "Requested radio is unavailable",
    RadioFailureCode.INVALID_CONTEXT: "Radio transmission context is invalid",
    RadioFailureCode.UNSUPPORTED_CAPABILITY: "Radio transport lacks a required capability",
    RadioFailureCode.TX_REJECTED: "Radio transmission was rejected",
    RadioFailureCode.TX_CANCELLED: "Radio transmission was cancelled",
    RadioFailureCode.TX_TIMEOUT: "Radio transmission timed out",
    RadioFailureCode.TRANSPORT_ERROR: "Radio transport failed",
}


def _failure(
    code: RadioFailureCode,
    message: str,
    transport_id: str | None = None,
    *,
    retryable: bool = False,
) -> RadioFailure:
    return RadioFailure(
        code=code,
        message=message,
        transport_id=transport_id,
        retryable=retryable,
    )


def _normalized_failure(failure: RadioFailure, transport_id: str) -> RadioFailure:
    return RadioFailure(
        code=failure.code,
        message=_GENERIC_FAILURE_MESSAGES[failure.code],
        transport_id=transport_id,
        retryable=failure.retryable,
    )


def _request_signature(request: RadioTransmissionRequest) -> str:
    payload = {
        "context": request.context.model_dump(mode="json"),
        "transport_id": request.transport_id,
        "audio": {
            "sample_rate_hz": request.audio.sample_rate_hz,
            "sample_format": request.audio.sample_format.value,
            "channels": request.audio.channels,
            "pcm_sha256": hashlib.sha256(request.audio.pcm).hexdigest(),
        },
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
