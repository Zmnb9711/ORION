"""Provider-neutral immutable contracts for Stage 6B radio transmission."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Protocol, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from orion.communication_contracts import CommunicationDomain, CommunicationPriority
from orion.interaction_contracts import ContextReference, CorrelationId


TransportId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    ),
]
RadioEntityId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]
OperationalCallsign = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
CoalitionIdentity = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    ),
]
SafeRadioMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]

MAX_FINALIZED_PCM_BYTES = 44_100 * 2 * 30


class _RadioModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RadioModulation(StrEnum):
    AM = "am"
    FM = "fm"


class PcmSampleFormat(StrEnum):
    SIGNED_16_LE = "pcm_s16le"


class RadioTransportCapability(StrEnum):
    TX_AUDIO = "tx_audio"
    TX_COMPLETION = "tx_completion"
    FREQUENCY = "frequency"
    MODULATION = "modulation"
    RX_AUDIO = "rx_audio"
    TRANSMISSION_CANCEL = "transmission_cancel"
    RADIO_SELECTION = "radio_selection"
    COALITION = "coalition"
    POSITIONAL_RADIO = "positional_radio"
    ENCRYPTION = "encryption"


REQUIRED_TX_CAPABILITIES = frozenset(
    {
        RadioTransportCapability.TX_AUDIO,
        RadioTransportCapability.TX_COMPLETION,
        RadioTransportCapability.FREQUENCY,
        RadioTransportCapability.MODULATION,
    }
)


class RadioReadiness(StrEnum):
    UNAVAILABLE = "unavailable"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class RadioFailureCode(StrEnum):
    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    NOT_READY = "not_ready"
    RADIO_UNAVAILABLE = "radio_unavailable"
    INVALID_CONTEXT = "invalid_context"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    TX_REJECTED = "tx_rejected"
    TX_CANCELLED = "tx_cancelled"
    TX_TIMEOUT = "tx_timeout"
    TRANSPORT_ERROR = "transport_error"


class RadioTransmissionState(StrEnum):
    QUEUED = "queued"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RadioAdapterOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RadioDiagnosticStage(StrEnum):
    ENQUEUED = "enqueued"
    REPLAYED = "replayed"
    REJECTED = "rejected"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RadioEntityRef(_RadioModel):
    """Logical speaker identity; it is not a mutable radio-entity registry."""

    entity_id: RadioEntityId
    operational_callsign: OperationalCallsign
    coalition: CoalitionIdentity | None = None


class RadioContext(_RadioModel):
    """One resolved transmission context, never a cockpit or telemetry store."""

    tx_correlation_id: CorrelationId
    source_domain: CommunicationDomain
    radio_entity: RadioEntityRef
    target_frequency_hz: float = Field(gt=0, le=100_000_000_000)
    modulation: RadioModulation
    communication_priority: CommunicationPriority
    interaction_id: UUID | None = None
    session_id: CorrelationId | None = None
    turn_id: CorrelationId | None = None
    provenance: tuple[ContextReference, ...] = ()

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if len(self.provenance) > 16:
            raise ValueError("RadioContext provenance exceeds the bounded limit")
        keys = [(item.context_type, item.reference_id) for item in self.provenance]
        if len(keys) != len(set(keys)):
            raise ValueError("RadioContext provenance references must be unique")
        return self


class FinalizedPcmAudio(_RadioModel):
    """Bounded finalized PCM accepted by the generic radio boundary."""

    pcm: bytes = Field(repr=False, min_length=2, max_length=MAX_FINALIZED_PCM_BYTES)
    sample_rate_hz: int = Field(ge=8_000, le=192_000)
    sample_format: PcmSampleFormat = PcmSampleFormat.SIGNED_16_LE
    channels: int = Field(default=1, ge=1, le=1)

    @model_validator(mode="after")
    def validate_alignment(self) -> Self:
        bytes_per_frame = 2 * self.channels
        if len(self.pcm) % bytes_per_frame:
            raise ValueError(
                "Finalized PCM must contain complete signed-16 sample frames"
            )
        return self


class RadioTransmissionRequest(_RadioModel):
    context: RadioContext
    audio: FinalizedPcmAudio = Field(repr=False)
    transport_id: TransportId | None = None


class RadioFailure(_RadioModel):
    code: RadioFailureCode
    message: SafeRadioMessage = Field(repr=False)
    transport_id: TransportId | None = None
    retryable: bool = False


class RadioTransportStatus(_RadioModel):
    transport_id: TransportId
    readiness: RadioReadiness
    detail: SafeRadioMessage | None = Field(default=None, repr=False)


class RadioAdapterTxResult(_RadioModel):
    tx_correlation_id: CorrelationId
    outcome: RadioAdapterOutcome
    started_at: datetime | None = None
    completed_at: datetime
    frame_count: int | None = Field(default=None, ge=0)
    duration_ms: float | None = Field(default=None, ge=0)
    failure: RadioFailure | None = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Radio adapter timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome is RadioAdapterOutcome.COMPLETED:
            if self.failure is not None:
                raise ValueError(
                    "Completed radio adapter result cannot contain failure"
                )
        elif self.failure is None:
            raise ValueError("Unsuccessful radio adapter result requires typed failure")
        if self.started_at is not None and self.completed_at < self.started_at:
            raise ValueError("Radio adapter completion cannot precede start")
        return self


class RadioTransmissionSnapshot(_RadioModel):
    tx_correlation_id: CorrelationId
    transport_id: TransportId
    state: RadioTransmissionState
    source_domain: CommunicationDomain
    radio_entity_id: RadioEntityId
    priority: CommunicationPriority
    target_frequency_hz: float
    modulation: RadioModulation
    enqueued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    frame_count: int | None = Field(default=None, ge=0)
    duration_ms: float | None = Field(default=None, ge=0)
    failure: RadioFailure | None = None

    @field_validator("enqueued_at", "started_at", "completed_at")
    @classmethod
    def require_aware_snapshot_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Radio transmission timestamps must be timezone-aware")
        return value


class RadioSubmissionResult(_RadioModel):
    accepted: bool
    replayed: bool = False
    transmission: RadioTransmissionSnapshot | None = None
    failure: RadioFailure | None = None

    @model_validator(mode="after")
    def validate_submission(self) -> Self:
        if self.accepted:
            if self.transmission is None or self.failure is not None:
                raise ValueError("Accepted radio submission requires transmission only")
        elif self.failure is None:
            raise ValueError("Rejected radio submission requires typed failure")
        return self


class RadioCancellationResult(_RadioModel):
    tx_correlation_id: CorrelationId
    cancelled: bool
    state: RadioTransmissionState | None = None
    failure: RadioFailure | None = None

    @model_validator(mode="after")
    def validate_cancellation(self) -> Self:
        if self.cancelled and self.failure is not None:
            raise ValueError("Successful cancellation cannot contain failure")
        if not self.cancelled and self.failure is None:
            raise ValueError("Unsuccessful cancellation requires typed failure")
        return self


class RadioRouterShutdownResult(_RadioModel):
    clean: bool
    already_stopped: bool = False
    queued_cancelled: int = Field(default=0, ge=0)
    adapters_stopped: int = Field(default=0, ge=0)
    adapter_shutdown_failures: int = Field(default=0, ge=0)
    worker_stopped: bool


class RadioDiagnosticEvent(_RadioModel):
    stage: RadioDiagnosticStage
    timestamp: datetime
    transport_id: TransportId
    tx_correlation_id: CorrelationId
    source_domain: CommunicationDomain
    radio_entity_id: RadioEntityId
    priority: CommunicationPriority
    target_frequency_hz: float
    modulation: RadioModulation
    failure_code: RadioFailureCode | None = None

    @field_validator("timestamp")
    @classmethod
    def require_aware_diagnostic_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Radio diagnostic timestamp must be timezone-aware")
        return value


class RadioTransportAdapter(Protocol):
    """Small synchronous transport boundary; mechanics remain adapter-owned."""

    transport_id: str

    def capabilities(self) -> frozenset[RadioTransportCapability]: ...

    def status(self) -> RadioTransportStatus: ...

    def start(self) -> RadioTransportStatus: ...

    def transmit(self, request: RadioTransmissionRequest) -> RadioAdapterTxResult: ...

    def cancel(self, tx_correlation_id: str) -> bool: ...

    def shutdown(self, timeout_s: float) -> bool: ...
