"""Provider-neutral immutable contracts for the IA-3 Tool Gateway."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    StringConstraints,
    field_validator,
    model_validator,
)

from orion.interaction_contracts import CapabilityId, CorrelationId, SemanticHint
from orion.world_model_contracts import (
    WorldFactAuthority,
    WorldFactSource,
    WorldFactStatus,
)


ToolName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        pattern=r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+$",
    ),
]
ToolVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=24,
        pattern=r"^[1-9][0-9]*\.[0-9]+$",
    ),
]
SchemaIdentity = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=200,
        pattern=r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+\.v[1-9][0-9]*$",
    ),
]
PermissionId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    ),
]
RuntimeModuleId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    ),
]
SafeMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]


class _ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ToolSchemaModel(_ToolModel):
    """Base for handler input/output models registered under a stable schema ID."""

    schema_identity: ClassVar[SchemaIdentity]


class ToolArguments(RootModel[dict[str, JsonValue]]):
    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def bounded_payload(self) -> Self:
        if len(self.root) > 64:
            raise ValueError("Tool arguments may contain at most 64 top-level fields")
        if len(json.dumps(self.root, ensure_ascii=False, separators=(",", ":"))) > 32_768:
            raise ValueError("Tool arguments exceed the 32 KiB boundary")
        return self


class ToolData(RootModel[dict[str, JsonValue]]):
    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def bounded_payload(self) -> Self:
        if len(self.root) > 128:
            raise ValueError("Tool data may contain at most 128 top-level fields")
        if len(json.dumps(self.root, ensure_ascii=False, separators=(",", ":"))) > 131_072:
            raise ValueError("Tool data exceeds the 128 KiB boundary")
        return self


class ToolAccessMode(StrEnum):
    READ = "read"
    WRITE = "write"


class ToolSideEffect(StrEnum):
    NONE = "none"
    CORE_STATE = "core_state"
    EXTERNAL_SYSTEM = "external_system"
    SIMULATOR = "simulator"


class ToolLatencyClass(StrEnum):
    LOCAL_FAST = "local_fast"
    LOCAL_QUERY = "local_query"
    EXTERNAL_OR_LONG = "external_or_long"
    ACTION = "action"


class ToolFreshnessPolicy(StrEnum):
    RETURN_SOURCE_STATUS = "return_source_status"
    REQUIRE_FRESH = "require_fresh"


class ToolPolicy(_ToolModel):
    required_permissions: tuple[PermissionId, ...] = ()
    required_module: RuntimeModuleId | None = None
    mission_required: bool = False
    freshness: ToolFreshnessPolicy = ToolFreshnessPolicy.RETURN_SOURCE_STATUS
    confirmation_required: bool = False
    idempotency_required: bool = False

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if len(self.required_permissions) != len(set(self.required_permissions)):
            raise ValueError("ToolPolicy permissions must be unique")
        return self


class ToolDefinition(_ToolModel):
    name: ToolName
    version: ToolVersion
    capability: CapabilityId
    description: SafeMessage
    input_schema: SchemaIdentity
    output_schema: SchemaIdentity
    access: ToolAccessMode
    latency_class: ToolLatencyClass
    side_effect: ToolSideEffect = ToolSideEffect.NONE
    policy: ToolPolicy = Field(default_factory=ToolPolicy)

    @model_validator(mode="after")
    def validate_safety_shape(self) -> Self:
        if self.access is ToolAccessMode.READ and self.side_effect is not ToolSideEffect.NONE:
            raise ValueError("read tools cannot declare side effects")
        if self.access is ToolAccessMode.WRITE and self.side_effect is ToolSideEffect.NONE:
            raise ValueError("write tools must declare their side-effect class")
        if self.policy.confirmation_required and self.access is not ToolAccessMode.WRITE:
            raise ValueError("confirmation is valid only for write tools")
        if self.policy.idempotency_required and self.access is not ToolAccessMode.WRITE:
            raise ValueError("idempotency is valid only for write tools")
        return self


class ExecutionContext(_ToolModel):
    actor_id: CorrelationId
    interaction_id: CorrelationId | None = None
    session_id: CorrelationId | None = None
    turn_id: CorrelationId | None = None
    task_id: CorrelationId | None = None
    provider_id: SemanticHint | None = None
    role: SemanticHint | None = None
    domain: SemanticHint | None = None
    allowed_capabilities: tuple[CapabilityId, ...] = ()
    permissions: tuple[PermissionId, ...] = ()
    confirmation_id: CorrelationId | None = None
    deadline: datetime | None = None
    cancelled: bool = False
    cancellation_id: CorrelationId | None = None

    @field_validator("deadline")
    @classmethod
    def require_aware_deadline(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("ExecutionContext.deadline must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if len(self.allowed_capabilities) != len(set(self.allowed_capabilities)):
            raise ValueError("allowed capabilities must be unique")
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("permissions must be unique")
        if self.cancelled and self.cancellation_id is None:
            raise ValueError("cancelled context requires cancellation_id")
        if not self.cancelled and self.cancellation_id is not None:
            raise ValueError("cancellation_id is valid only for cancelled context")
        return self


class ToolCall(_ToolModel):
    call_id: CorrelationId
    name: ToolName
    version: ToolVersion
    arguments: ToolArguments = Field(default_factory=lambda: ToolArguments(root={}))
    context: ExecutionContext
    idempotency_key: CorrelationId | None = None


class ToolErrorCode(StrEnum):
    TOOL_NOT_FOUND = "tool_not_found"
    UNSUPPORTED_TOOL_VERSION = "unsupported_tool_version"
    INVALID_ARGUMENTS = "invalid_arguments"
    CAPABILITY_NOT_ALLOWED = "capability_not_allowed"
    MODULE_UNAVAILABLE = "module_unavailable"
    MODULE_DISABLED = "module_disabled"
    MISSION_UNAVAILABLE = "mission_unavailable"
    DATA_UNAVAILABLE = "data_unavailable"
    DATA_STALE = "data_stale"
    DATA_RESTRICTED = "data_restricted"
    PERMISSION_DENIED = "permission_denied"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_INVALID = "confirmation_invalid"
    IDEMPOTENCY_REQUIRED = "idempotency_required"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
    HANDLER_FAILURE = "handler_failure"


class ToolErrorCategory(StrEnum):
    LOOKUP = "lookup"
    VALIDATION = "validation"
    POLICY = "policy"
    AVAILABILITY = "availability"
    FRESHNESS = "freshness"
    LIFECYCLE = "lifecycle"
    EXECUTION = "execution"


class ToolError(_ToolModel):
    code: ToolErrorCode
    category: ToolErrorCategory
    message: SafeMessage = Field(repr=False)
    retryable: bool = False


class ToolResultStatus(StrEnum):
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolReceiptStatus(StrEnum):
    QUEUED = "queued"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolProvenance(_ToolModel):
    sources: tuple[WorldFactSource, ...] = ()
    authorities: tuple[WorldFactAuthority, ...] = ()
    fact_statuses: tuple[WorldFactStatus, ...] = ()
    max_age_seconds: float | None = Field(default=None, ge=0)
    generations: tuple[int | str, ...] = ()


class ToolReceipt(_ToolModel):
    call_id: CorrelationId
    tool_name: ToolName
    tool_version: ToolVersion
    status: ToolReceiptStatus
    actor_id: CorrelationId
    interaction_id: CorrelationId | None = None
    session_id: CorrelationId | None = None
    turn_id: CorrelationId | None = None
    task_id: CorrelationId | None = None
    idempotency_key: CorrelationId | None = None
    accepted_at: datetime
    completed_at: datetime
    latency_ms: float = Field(ge=0)
    handler_started: bool

    @field_validator("accepted_at", "completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ToolReceipt timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_timeline(self) -> Self:
        if self.completed_at < self.accepted_at:
            raise ValueError("ToolReceipt completion cannot precede acceptance")
        return self


class ToolResult(_ToolModel):
    schema_version: Literal["ia3.tool.v1"] = "ia3.tool.v1"
    call_id: CorrelationId
    tool_name: ToolName
    tool_version: ToolVersion
    capability: CapabilityId | None = None
    status: ToolResultStatus
    data: ToolData | None = Field(default=None, repr=False)
    output_schema: SchemaIdentity | None = None
    provenance: ToolProvenance | None = None
    warnings: tuple[SafeMessage, ...] = ()
    error: ToolError | None = None
    receipt: ToolReceipt

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        if self.status is ToolResultStatus.COMPLETED:
            if self.data is None or self.output_schema is None or self.error is not None:
                raise ValueError("completed ToolResult requires typed data and no error")
        elif self.data is not None or self.output_schema is not None or self.error is None:
            raise ValueError("non-completed ToolResult requires an error and no data")
        return self


class ToolDiagnosticStage(StrEnum):
    RECEIVED = "received"
    POLICY_REJECTED = "policy_rejected"
    HANDLER_STARTED = "handler_started"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolDiagnosticEvent(_ToolModel):
    schema_version: Literal["ia3.tool-diagnostic.v1"] = "ia3.tool-diagnostic.v1"
    stage: ToolDiagnosticStage
    timestamp: datetime
    call_id: CorrelationId
    tool_name: ToolName
    tool_version: ToolVersion
    capability: CapabilityId | None = None
    actor_id: CorrelationId
    interaction_id: CorrelationId | None = None
    session_id: CorrelationId | None = None
    decision: ToolErrorCode | Literal["allowed", "completed"] | None = None
    latency_ms: float | None = Field(default=None, ge=0)

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Tool diagnostic timestamps must be timezone-aware")
        return value
