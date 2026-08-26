"""Provider-neutral immutable contracts for IA-4 planner orchestration."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from orion.interaction_contracts import (
    CapabilityId,
    CorrelationId,
    InteractionRequest,
    SemanticHint,
    SemanticResponse,
    SemanticText,
)
from orion.tool_gateway_contracts import (
    ToolArguments,
    ToolDefinition,
    ToolName,
    ToolReceipt,
    ToolVersion,
)


ProviderIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    ),
]
ModelIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
SafePlannerMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]


class _PlannerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PlannerTaskStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_TOOLS = "waiting_for_tools"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class PlannerErrorCode(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_PROTOCOL_ERROR = "provider_protocol_error"
    INVALID_PROVIDER_EVENT = "invalid_provider_event"
    INVALID_TOOL_REQUEST = "invalid_tool_request"
    TOOL_CALL_REJECTED = "tool_call_rejected"
    TOOL_ROUND_LIMIT_EXCEEDED = "tool_round_limit_exceeded"
    INVALID_FINAL_RESPONSE = "invalid_final_response"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
    INTERNAL_PLANNER_ERROR = "internal_planner_error"


class PlannerErrorCategory(StrEnum):
    PROVIDER = "provider"
    PROTOCOL = "protocol"
    TOOL = "tool"
    VALIDATION = "validation"
    LIFECYCLE = "lifecycle"
    INTERNAL = "internal"


class PlannerError(_PlannerModel):
    code: PlannerErrorCode
    category: PlannerErrorCategory
    message: SafePlannerMessage = Field(repr=False)
    retryable: bool = False


class ProviderRetryPolicy(_PlannerModel):
    """Core-owned bound passed to a future adapter; IA-4 performs no HTTP retry."""

    max_attempts: int = Field(default=1, ge=1, le=3)
    retryable_codes: tuple[PlannerErrorCode, ...] = (
        PlannerErrorCode.PROVIDER_UNAVAILABLE,
        PlannerErrorCode.PROVIDER_TIMEOUT,
    )

    @model_validator(mode="after")
    def validate_codes(self) -> Self:
        if len(self.retryable_codes) != len(set(self.retryable_codes)):
            raise ValueError("Provider retry codes must be unique")
        allowed = {
            PlannerErrorCode.PROVIDER_UNAVAILABLE,
            PlannerErrorCode.PROVIDER_TIMEOUT,
        }
        if not set(self.retryable_codes).issubset(allowed):
            raise ValueError("Only transient provider failures may be retryable")
        return self


class PlannerUsage(_PlannerModel):
    model_identifier: ModelIdentifier | None = None
    provider_request_ids: tuple[CorrelationId, ...] = ()
    input_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    cached_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    provider_attempts: int | None = Field(default=None, ge=1, le=100)
    provider_latency_ms: float | None = Field(default=None, ge=0)
    tool_wait_latency_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_request_ids(self) -> Self:
        if len(self.provider_request_ids) > 32:
            raise ValueError("Provider request ID list exceeds the bounded limit")
        if len(self.provider_request_ids) != len(set(self.provider_request_ids)):
            raise ValueError("Provider request IDs must be unique")
        return self


class PlannerExecutionPolicy(_PlannerModel):
    actor_id: CorrelationId
    provider_id: ProviderIdentifier
    permissions: tuple[SemanticHint, ...] = ()
    core_instructions: tuple[SemanticText, ...] = ()
    deadline: datetime
    max_tool_rounds: int = Field(default=4, ge=0, le=16)
    provider_retry: ProviderRetryPolicy = Field(default_factory=ProviderRetryPolicy)

    @field_validator("deadline")
    @classmethod
    def require_aware_deadline(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Planner deadline must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("Planner permissions must be unique")
        if len(self.core_instructions) > 16:
            raise ValueError("Core planning instructions exceed the bounded limit")
        return self


class PlannerProviderRequest(_PlannerModel):
    schema_version: Literal["ia4.planner-request.v1"] = "ia4.planner-request.v1"
    planner_task_id: CorrelationId
    interaction: InteractionRequest = Field(repr=False)
    allowed_capabilities: tuple[CapabilityId, ...]
    available_tools: tuple[ToolDefinition, ...] = ()
    core_instructions: tuple[SemanticText, ...] = Field(default=(), repr=False)
    deadline: datetime
    retry_policy: ProviderRetryPolicy

    @field_validator("deadline")
    @classmethod
    def require_aware_deadline(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Planner provider deadline must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if self.allowed_capabilities != self.interaction.allowed_capabilities:
            raise ValueError("Provider request capabilities must match Core interaction policy")
        keys = [(item.name, item.version) for item in self.available_tools]
        if len(keys) != len(set(keys)):
            raise ValueError("Available planner tools must be unique")
        if any(item.capability not in self.allowed_capabilities for item in self.available_tools):
            raise ValueError("Available planner tool exceeds allowed capabilities")
        if len(self.available_tools) > 64:
            raise ValueError("Available planner tool catalog exceeds the bounded limit")
        return self


class PlannerToolRequest(_PlannerModel):
    call_id: CorrelationId
    name: ToolName
    version: ToolVersion
    arguments: ToolArguments = Field(default_factory=lambda: ToolArguments(root={}), repr=False)
    idempotency_key: CorrelationId | None = None


class PlannerEventKind(StrEnum):
    STARTED = "planner_started"
    TOOL_CALLS_REQUESTED = "tool_calls_requested"
    FINAL_RESPONSE = "final_response"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class PlannerStartedEvent(_PlannerModel):
    kind: Literal[PlannerEventKind.STARTED] = PlannerEventKind.STARTED
    event_id: CorrelationId
    usage: PlannerUsage | None = None


class PlannerToolCallsEvent(_PlannerModel):
    kind: Literal[PlannerEventKind.TOOL_CALLS_REQUESTED] = PlannerEventKind.TOOL_CALLS_REQUESTED
    event_id: CorrelationId
    calls: tuple[PlannerToolRequest, ...] = Field(min_length=1, max_length=8)
    usage: PlannerUsage | None = None


class PlannerFinalResponseEvent(_PlannerModel):
    kind: Literal[PlannerEventKind.FINAL_RESPONSE] = PlannerEventKind.FINAL_RESPONSE
    event_id: CorrelationId
    response: SemanticResponse = Field(repr=False)
    usage: PlannerUsage | None = None


class PlannerFailedEvent(_PlannerModel):
    kind: Literal[PlannerEventKind.FAILED] = PlannerEventKind.FAILED
    event_id: CorrelationId
    error: PlannerError
    usage: PlannerUsage | None = None

    @model_validator(mode="after")
    def require_provider_failure(self) -> Self:
        allowed = {
            PlannerErrorCode.PROVIDER_UNAVAILABLE,
            PlannerErrorCode.PROVIDER_TIMEOUT,
            PlannerErrorCode.PROVIDER_PROTOCOL_ERROR,
        }
        if self.error.code not in allowed:
            raise ValueError("Provider failure event cannot claim Core lifecycle or tool failures")
        return self


class PlannerCancelledEvent(_PlannerModel):
    kind: Literal[PlannerEventKind.CANCELLED] = PlannerEventKind.CANCELLED
    event_id: CorrelationId
    reason: SafePlannerMessage = "Provider run acknowledged cancellation."
    usage: PlannerUsage | None = None


class PlannerTimedOutEvent(_PlannerModel):
    kind: Literal[PlannerEventKind.TIMED_OUT] = PlannerEventKind.TIMED_OUT
    event_id: CorrelationId
    reason: SafePlannerMessage = "Provider run timed out."
    usage: PlannerUsage | None = None


PlannerEvent = (
    PlannerStartedEvent
    | PlannerToolCallsEvent
    | PlannerFinalResponseEvent
    | PlannerFailedEvent
    | PlannerCancelledEvent
    | PlannerTimedOutEvent
)


class PlannerTaskSnapshot(_PlannerModel):
    schema_version: Literal["ia4.planner-task.v1"] = "ia4.planner-task.v1"
    planner_task_id: CorrelationId
    interaction_id: UUID
    session_id: CorrelationId | None = None
    turn_id: CorrelationId | None = None
    provider_id: ProviderIdentifier
    allowed_capabilities: tuple[CapabilityId, ...]
    status: PlannerTaskStatus
    created_at: datetime
    deadline: datetime
    completed_at: datetime | None = None
    tool_rounds: int = Field(default=0, ge=0, le=16)
    requested_call_ids: tuple[CorrelationId, ...] = ()
    completed_tool_receipts: tuple[ToolReceipt, ...] = ()
    final_response_id: UUID | None = None
    error: PlannerError | None = None
    usage: PlannerUsage | None = None
    total_latency_ms: float = Field(default=0, ge=0)

    @field_validator("created_at", "deadline", "completed_at")
    @classmethod
    def require_aware_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Planner task timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        terminal = {
            PlannerTaskStatus.COMPLETED,
            PlannerTaskStatus.FAILED,
            PlannerTaskStatus.CANCELLED,
            PlannerTaskStatus.TIMED_OUT,
        }
        if self.status in terminal and self.completed_at is None:
            raise ValueError("Terminal planner task requires completed_at")
        if self.status not in terminal and self.completed_at is not None:
            raise ValueError("Non-terminal planner task cannot have completed_at")
        if self.status is PlannerTaskStatus.COMPLETED:
            if self.final_response_id is None or self.error is not None:
                raise ValueError("Completed planner task requires a final response and no error")
        elif self.status in terminal and self.error is None:
            raise ValueError("Non-success terminal planner task requires an error")
        if len(self.requested_call_ids) != len(set(self.requested_call_ids)):
            raise ValueError("Planner requested call IDs must be unique")
        return self


class PlannerExecutionResult(_PlannerModel):
    schema_version: Literal["ia4.planner-result.v1"] = "ia4.planner-result.v1"
    task: PlannerTaskSnapshot
    response: SemanticResponse | None = Field(default=None, repr=False)
    error: PlannerError | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.task.status is PlannerTaskStatus.COMPLETED:
            if self.response is None or self.error is not None:
                raise ValueError("Successful planner result requires response and no error")
        elif self.response is not None or self.error is None:
            raise ValueError("Unsuccessful planner result requires error and no response")
        return self


class PlannerDiagnosticStage(StrEnum):
    TASK_CREATED = "task_created"
    PROVIDER_STARTED = "provider_started"
    TOOL_REQUESTED = "tool_requested"
    TOOL_RESULT = "tool_result"
    CONTINUATION_STARTED = "continuation_started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class PlannerDiagnosticEvent(_PlannerModel):
    schema_version: Literal["ia4.planner-diagnostic.v1"] = "ia4.planner-diagnostic.v1"
    stage: PlannerDiagnosticStage
    timestamp: datetime
    planner_task_id: CorrelationId
    interaction_id: UUID
    provider_id: ProviderIdentifier
    event_id: CorrelationId | None = None
    call_id: CorrelationId | None = None
    tool_name: ToolName | None = None
    decision: PlannerErrorCode | Literal["accepted", "completed"] | None = None
    latency_ms: float | None = Field(default=None, ge=0)

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Planner diagnostic timestamp must be timezone-aware")
        return value
