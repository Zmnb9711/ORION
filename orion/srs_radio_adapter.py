"""Thin production adapter from generic radio contracts to proven SRS TX."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol

from orion.radio_contracts import (
    REQUIRED_TX_CAPABILITIES,
    PcmSampleFormat,
    RadioAdapterOutcome,
    RadioAdapterTxResult,
    RadioFailure,
    RadioFailureCode,
    RadioModulation,
    RadioReadiness,
    RadioTransmissionRequest,
    RadioTransportCapability,
    RadioTransportStatus,
)
from orion.srs_protocol import AM, FM
from orion.srs_radio_transport import SrsState


SRS_ADAPTER_ID = "srs"
SRS_PCM_INPUT_RATE = 44_100


@dataclass(frozen=True, slots=True)
class SrsAdapterRuntime:
    """Safe SRS runtime projection kept below the generic boundary."""

    state: SrsState
    endpoint_started: bool
    radio_registered: bool
    udp_registered: bool
    frequency_hz: float
    modulation: int
    bot_name: str
    coalition: int
    failed: bool = False


@dataclass(frozen=True, slots=True)
class SrsTxCompletion:
    """Existing SRS tx_completed-equivalent timing and frame result."""

    queue_to_first_tx_ms: float
    queue_to_complete_ms: float
    frame_count: int
    duration_ms: float


class SrsTransmissionPort(Protocol):
    """Narrow seam implemented by the existing SRS/Yandex PCM endpoint."""

    def srs_adapter_runtime(self) -> SrsAdapterRuntime: ...

    def transmit_srs_pcm(
        self,
        tx_correlation_id: str,
        pcm44: bytes,
        timeout_s: float,
    ) -> SrsTxCompletion: ...

    def shutdown_srs_adapter(self, timeout_s: float) -> bool: ...


AdapterDiagnostic = Callable[[str, dict[str, object]], None]


class SrsRadioTransportAdapter:
    """Expose one existing SRS endpoint as a Stage 6B.1 transport adapter."""

    transport_id = SRS_ADAPTER_ID

    def __init__(
        self,
        port: SrsTransmissionPort,
        *,
        diagnostic: AdapterDiagnostic | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._port = port
        self._diagnostic = diagnostic or (lambda _event, _fields: None)
        self._clock = clock
        self._started = False
        self._stopped = False

    def capabilities(self) -> frozenset[RadioTransportCapability]:
        return REQUIRED_TX_CAPABILITIES

    def status(self) -> RadioTransportStatus:
        if self._stopped:
            return RadioTransportStatus(
                transport_id=self.transport_id,
                readiness=RadioReadiness.STOPPED,
            )
        try:
            runtime = self._port.srs_adapter_runtime()
        except Exception:
            return RadioTransportStatus(
                transport_id=self.transport_id,
                readiness=RadioReadiness.ERROR,
                detail="SRS transport status is unavailable",
            )
        return RadioTransportStatus(
            transport_id=self.transport_id,
            readiness=map_srs_readiness(runtime),
        )

    def start(self) -> RadioTransportStatus:
        if self._stopped:
            return RadioTransportStatus(
                transport_id=self.transport_id,
                readiness=RadioReadiness.STOPPED,
            )
        self._started = True
        status = self.status()
        self._record("srs_adapter_started", readiness=status.readiness.value)
        return status

    def transmit(self, request: RadioTransmissionRequest) -> RadioAdapterTxResult:
        tx_id = str(request.context.tx_correlation_id)
        began_at = self._now()
        if not self._started or self._stopped:
            return _failed_result(
                tx_id,
                RadioFailureCode.NOT_READY,
                "SRS radio adapter is not started",
                began_at,
            )
        status = self.status()
        if status.readiness is not RadioReadiness.READY:
            code = (
                RadioFailureCode.TRANSPORT_UNAVAILABLE
                if status.readiness is RadioReadiness.UNAVAILABLE
                else RadioFailureCode.NOT_READY
            )
            return _failed_result(
                tx_id, code, "SRS radio transport is not ready", began_at
            )
        try:
            runtime = self._port.srs_adapter_runtime()
            failure = validate_srs_request(request, runtime)
            if failure is not None:
                self._record(
                    "srs_adapter_tx_failed",
                    tx_correlation_id=tx_id,
                    failure_code=failure.code.value,
                )
                return RadioAdapterTxResult(
                    tx_correlation_id=tx_id,
                    outcome=RadioAdapterOutcome.FAILED,
                    completed_at=began_at,
                    failure=failure,
                )
            self._record(
                "srs_adapter_tx_started",
                tx_correlation_id=tx_id,
                frequency_hz=request.context.target_frequency_hz,
                modulation=request.context.modulation.value,
                radio_entity_id=request.context.radio_entity.entity_id,
            )
            completion = self._port.transmit_srs_pcm(
                tx_id,
                request.audio.pcm,
                request.timeout_s,
            )
            first_tx_at = began_at + timedelta(
                milliseconds=completion.queue_to_first_tx_ms
            )
            completed_at = began_at + timedelta(
                milliseconds=completion.queue_to_complete_ms
            )
            self._record(
                "srs_adapter_tx_completed",
                tx_correlation_id=tx_id,
                frames=completion.frame_count,
                duration_ms=completion.duration_ms,
            )
            return RadioAdapterTxResult(
                tx_correlation_id=tx_id,
                outcome=RadioAdapterOutcome.COMPLETED,
                started_at=first_tx_at,
                completed_at=completed_at,
                frame_count=completion.frame_count,
                duration_ms=completion.duration_ms,
            )
        except TimeoutError:
            code = RadioFailureCode.TX_TIMEOUT
            message = "SRS radio transmission timed out"
        except (ConnectionError, OSError):
            code = RadioFailureCode.TRANSPORT_UNAVAILABLE
            message = "SRS radio transport became unavailable"
        except RuntimeError:
            try:
                failed_runtime = self._port.srs_adapter_runtime()
                transport_failed = failed_runtime.failed or (
                    failed_runtime.state is SrsState.ERROR
                )
            except Exception:
                transport_failed = True
            if transport_failed:
                code = RadioFailureCode.TRANSPORT_ERROR
                message = "SRS radio transport failed"
            else:
                code = RadioFailureCode.TX_REJECTED
                message = "SRS radio transmission was rejected"
        except Exception:
            code = RadioFailureCode.TRANSPORT_ERROR
            message = "SRS radio transport failed"
        self._record(
            "srs_adapter_tx_failed",
            tx_correlation_id=tx_id,
            failure_code=code.value,
        )
        return _failed_result(tx_id, code, message, self._now())

    def cancel(self, tx_correlation_id: str) -> bool:
        self._record(
            "srs_adapter_cancel_unsupported",
            tx_correlation_id=tx_correlation_id,
        )
        return False

    def shutdown(self, timeout_s: float) -> bool:
        if self._stopped:
            return True
        try:
            stopped = self._port.shutdown_srs_adapter(timeout_s)
        except Exception:
            stopped = False
        self._stopped = True
        self._record("srs_adapter_stopped", clean=stopped)
        return stopped

    def _record(self, event: str, **fields: object) -> None:
        self._diagnostic(event, fields)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("SRS adapter clock must return timezone-aware timestamps")
        return value


def map_srs_readiness(runtime: SrsAdapterRuntime) -> RadioReadiness:
    if runtime.failed or runtime.state is SrsState.ERROR:
        return RadioReadiness.ERROR
    if runtime.state is SrsState.STOPPING:
        return RadioReadiness.STOPPING
    if runtime.state is SrsState.STOPPED:
        return RadioReadiness.STOPPED
    if runtime.state is SrsState.DISCONNECTED:
        return RadioReadiness.UNAVAILABLE
    if runtime.state is SrsState.READY:
        if (
            runtime.endpoint_started
            and runtime.radio_registered
            and runtime.udp_registered
        ):
            return RadioReadiness.READY
        return RadioReadiness.DEGRADED
    return RadioReadiness.STARTING


def radio_modulation_from_srs(value: int) -> RadioModulation:
    if value == AM:
        return RadioModulation.AM
    if value == FM:
        return RadioModulation.FM
    raise ValueError("SRS modulation is unsupported by the generic radio adapter")


def radio_modulation_to_srs(value: RadioModulation) -> int:
    return AM if value is RadioModulation.AM else FM


def validate_srs_request(
    request: RadioTransmissionRequest,
    runtime: SrsAdapterRuntime,
) -> RadioFailure | None:
    context = request.context
    if request.audio.sample_format is not PcmSampleFormat.SIGNED_16_LE:
        return _failure(
            RadioFailureCode.UNSUPPORTED_CAPABILITY,
            "SRS adapter supports signed PCM16LE only",
        )
    if (
        request.audio.sample_rate_hz != SRS_PCM_INPUT_RATE
        or request.audio.channels != 1
    ):
        return _failure(
            RadioFailureCode.UNSUPPORTED_CAPABILITY,
            "SRS adapter supports finalized mono PCM at 44.1 kHz",
        )
    if abs(context.target_frequency_hz - runtime.frequency_hz) > 1e-6:
        return _failure(
            RadioFailureCode.RADIO_UNAVAILABLE,
            "Requested frequency is not registered on this SRS endpoint",
        )
    if radio_modulation_to_srs(context.modulation) != runtime.modulation:
        return _failure(
            RadioFailureCode.RADIO_UNAVAILABLE,
            "Requested modulation is not registered on this SRS endpoint",
        )
    if context.radio_entity.operational_callsign.strip() != runtime.bot_name.strip():
        return _failure(
            RadioFailureCode.RADIO_UNAVAILABLE,
            "Requested radio entity is not registered on this SRS endpoint",
        )
    expected_coalition = {1: "red", 2: "blue"}.get(runtime.coalition)
    if (
        context.radio_entity.coalition is not None
        and context.radio_entity.coalition != expected_coalition
    ):
        return _failure(
            RadioFailureCode.RADIO_UNAVAILABLE,
            "Requested coalition does not match this SRS endpoint",
        )
    return None


def _failure(code: RadioFailureCode, message: str) -> RadioFailure:
    return RadioFailure(
        code=code,
        message=message,
        transport_id=SRS_ADAPTER_ID,
        retryable=code
        in {
            RadioFailureCode.NOT_READY,
            RadioFailureCode.TRANSPORT_UNAVAILABLE,
            RadioFailureCode.TX_TIMEOUT,
        },
    )


def _failed_result(
    tx_correlation_id: str,
    code: RadioFailureCode,
    message: str,
    completed_at: datetime,
) -> RadioAdapterTxResult:
    return RadioAdapterTxResult(
        tx_correlation_id=tx_correlation_id,
        outcome=RadioAdapterOutcome.FAILED,
        completed_at=completed_at,
        failure=_failure(code, message),
    )
