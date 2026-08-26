"""IA-3 Core-owned Tool Gateway and its initial read-only World Model tools."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Generic, Protocol, TypeVar, cast

from pydantic import BaseModel, Field, ValidationError

from orion.interaction_contracts import CapabilityId
from orion.runtime_modules import OrionRuntimeModule, RuntimeModuleRegistry, runtime_modules
from orion.tool_gateway_contracts import (
    ExecutionContext,
    ToolAccessMode,
    ToolArguments,
    ToolCall,
    ToolData,
    ToolDefinition,
    ToolDiagnosticEvent,
    ToolDiagnosticStage,
    ToolError,
    ToolErrorCategory,
    ToolErrorCode,
    ToolFreshnessPolicy,
    ToolLatencyClass,
    ToolPolicy,
    ToolProvenance,
    ToolReceipt,
    ToolReceiptStatus,
    ToolResult,
    ToolResultStatus,
    ToolSchemaModel,
    ToolSideEffect,
)
from orion.world_model import WorldModelFacade, world_model
from orion.world_model_contracts import (
    GeometryToUnitQuery,
    GeometryToUnitSnapshot,
    MissionIdentitySnapshot,
    MissionUnitsQuery,
    MissionUnitsSnapshot,
    ObservedContactsSnapshot,
    OwnshipNavigationSnapshot,
    OwnshipSnapshot,
    WorldFact,
    WorldFactAuthority,
    WorldFactSource,
    WorldFactStatus,
)


logger = logging.getLogger(__name__)

InputModel = TypeVar("InputModel", bound=ToolSchemaModel)
OutputModel = TypeVar("OutputModel", bound=ToolSchemaModel)
ToolHandler = Callable[[InputModel, ExecutionContext], OutputModel]


class ConfirmationPolicy(Protocol):
    def validate(
        self,
        confirmation_id: str,
        call: ToolCall,
        definition: ToolDefinition,
    ) -> bool: ...


class DenyUnboundConfirmations:
    """Fail closed until confirmation IDs gain actor/session/tool binding."""

    def validate(
        self,
        confirmation_id: str,
        call: ToolCall,
        definition: ToolDefinition,
    ) -> bool:
        del confirmation_id, call, definition
        return False


@dataclass(frozen=True, slots=True)
class _RegisteredTool(Generic[InputModel, OutputModel]):
    definition: ToolDefinition
    input_model: type[InputModel]
    output_model: type[OutputModel]
    handler: ToolHandler[InputModel, OutputModel]


class ToolRegistry:
    """Deterministic registry; a name/version pair can never be replaced."""

    def __init__(self) -> None:
        self._tools: dict[tuple[str, str], _RegisteredTool] = {}  # type: ignore[type-arg]
        self._lock = RLock()

    def register(
        self,
        definition: ToolDefinition,
        input_model: type[InputModel],
        output_model: type[OutputModel],
        handler: ToolHandler[InputModel, OutputModel],
    ) -> None:
        if input_model.schema_identity != definition.input_schema:
            raise ValueError("Tool input model does not match definition schema")
        if output_model.schema_identity != definition.output_schema:
            raise ValueError("Tool output model does not match definition schema")
        key = (definition.name, definition.version)
        registration = _RegisteredTool(
            definition=definition,
            input_model=input_model,
            output_model=output_model,
            handler=handler,
        )
        with self._lock:
            if key in self._tools:
                raise ValueError(f"Tool already registered: {definition.name}@{definition.version}")
            self._tools[key] = registration

    def resolve(self, name: str, version: str) -> _RegisteredTool | None:  # type: ignore[type-arg]
        with self._lock:
            return self._tools.get((name, version))

    def has_name(self, name: str) -> bool:
        with self._lock:
            return any(registered_name == name for registered_name, _ in self._tools)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        with self._lock:
            return tuple(
                item.definition
                for _, item in sorted(self._tools.items(), key=lambda pair: pair[0])
            )


class ToolGatewayDiagnostics:
    """Bounded scalar lifecycle evidence; arguments and results are never stored."""

    def __init__(self, max_events: int = 500) -> None:
        if max_events <= 0:
            raise ValueError("Tool diagnostics max_events must be positive")
        self._events: deque[ToolDiagnosticEvent] = deque(maxlen=max_events)
        self._lock = RLock()

    def record(self, event: ToolDiagnosticEvent) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> tuple[ToolDiagnosticEvent, ...]:
        with self._lock:
            return tuple(self._events)


class ToolGateway:
    """Validate, authorize and execute one registered Core tool call."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        world: WorldModelFacade = world_model,
        modules: RuntimeModuleRegistry = runtime_modules,
        confirmations: ConfirmationPolicy | None = None,
        diagnostics: ToolGatewayDiagnostics | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._registry = registry
        self._world = world
        self._modules = modules
        self._confirmations = confirmations or DenyUnboundConfirmations()
        self._diagnostics = diagnostics or ToolGatewayDiagnostics()
        self._clock = clock
        self._monotonic = monotonic

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._registry.definitions()

    def diagnostic_snapshot(self) -> tuple[ToolDiagnosticEvent, ...]:
        return self._diagnostics.snapshot()

    def execute(self, call: ToolCall) -> ToolResult:
        accepted_at = self._now()
        started = self._monotonic()
        self._diagnostic(ToolDiagnosticStage.RECEIVED, call, accepted_at)
        registration = self._registry.resolve(call.name, call.version)
        if registration is None:
            code = (
                ToolErrorCode.UNSUPPORTED_TOOL_VERSION
                if self._registry.has_name(call.name)
                else ToolErrorCode.TOOL_NOT_FOUND
            )
            return self._reject(call, accepted_at, started, code)
        definition = registration.definition

        rejection = self._evaluate_policy(call, definition, accepted_at)
        if rejection is not None:
            return self._reject(call, accepted_at, started, rejection, definition=definition)

        try:
            arguments = registration.input_model.model_validate(call.arguments.root)
        except ValidationError:
            return self._reject(
                call,
                accepted_at,
                started,
                ToolErrorCode.INVALID_ARGUMENTS,
                definition=definition,
            )

        self._diagnostic(
            ToolDiagnosticStage.HANDLER_STARTED,
            call,
            self._now(),
            capability=definition.capability,
            decision="allowed",
        )
        try:
            raw_output = registration.handler(arguments, call.context)
            output = registration.output_model.model_validate(raw_output.model_dump())
        except Exception:
            logger.error("IA-3 tool handler failed safely: %s@%s", call.name, call.version)
            return self._failure(call, accepted_at, started, definition)

        provenance = self._provenance(output)
        if (
            definition.policy.freshness is ToolFreshnessPolicy.REQUIRE_FRESH
            and WorldFactStatus.STALE in provenance.fact_statuses
        ):
            return self._reject(
                call,
                accepted_at,
                started,
                ToolErrorCode.DATA_STALE,
                definition=definition,
                handler_started=True,
            )
        try:
            data = ToolData.model_validate(output.model_dump(mode="json"))
        except ValidationError:
            return self._failure(call, accepted_at, started, definition)

        completed_at = self._now()
        latency = self._latency(started)
        warnings = tuple(
            warning
            for status, warning in (
                (WorldFactStatus.STALE, "source_status_stale"),
                (WorldFactStatus.RESTRICTED, "source_status_restricted"),
                (WorldFactStatus.UNAVAILABLE, "source_status_unavailable"),
                (WorldFactStatus.UNKNOWN, "source_status_unknown"),
            )
            if status in provenance.fact_statuses
        )
        result = ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            tool_version=call.version,
            capability=definition.capability,
            status=ToolResultStatus.COMPLETED,
            data=data,
            output_schema=definition.output_schema,
            provenance=provenance,
            warnings=warnings,
            receipt=self._receipt(
                call,
                accepted_at,
                completed_at,
                latency,
                ToolReceiptStatus.COMPLETED,
                handler_started=True,
            ),
        )
        self._diagnostic(
            ToolDiagnosticStage.COMPLETED,
            call,
            completed_at,
            capability=definition.capability,
            decision="completed",
            latency_ms=latency,
        )
        return result

    def _evaluate_policy(
        self,
        call: ToolCall,
        definition: ToolDefinition,
        now: datetime,
    ) -> ToolErrorCode | None:
        context = call.context
        if context.cancelled:
            return ToolErrorCode.CANCELLED
        if context.deadline is not None and now >= context.deadline:
            return ToolErrorCode.DEADLINE_EXCEEDED
        if definition.capability not in context.allowed_capabilities:
            return ToolErrorCode.CAPABILITY_NOT_ALLOWED
        if not set(definition.policy.required_permissions).issubset(context.permissions):
            return ToolErrorCode.PERMISSION_DENIED
        if definition.policy.required_module is not None:
            try:
                module = OrionRuntimeModule(definition.policy.required_module)
            except ValueError:
                return ToolErrorCode.MODULE_UNAVAILABLE
            status = self._modules.status(module)
            if not status.available:
                return ToolErrorCode.MODULE_UNAVAILABLE
            if not status.enabled:
                return ToolErrorCode.MODULE_DISABLED
        if definition.policy.mission_required:
            mission = self._world.mission_identity().mission
            if mission.status is WorldFactStatus.STALE:
                if definition.policy.freshness is ToolFreshnessPolicy.REQUIRE_FRESH:
                    return ToolErrorCode.DATA_STALE
            elif mission.status is not WorldFactStatus.KNOWN:
                return ToolErrorCode.MISSION_UNAVAILABLE
        if definition.policy.confirmation_required:
            if context.confirmation_id is None:
                return ToolErrorCode.CONFIRMATION_REQUIRED
            if not self._confirmations.validate(context.confirmation_id, call, definition):
                return ToolErrorCode.CONFIRMATION_INVALID
        if definition.policy.idempotency_required and call.idempotency_key is None:
            return ToolErrorCode.IDEMPOTENCY_REQUIRED
        return None

    def _reject(
        self,
        call: ToolCall,
        accepted_at: datetime,
        started: float,
        code: ToolErrorCode,
        *,
        definition: ToolDefinition | None = None,
        handler_started: bool = False,
    ) -> ToolResult:
        completed_at = self._now()
        latency = self._latency(started)
        result_status = (
            ToolResultStatus.CANCELLED
            if code is ToolErrorCode.CANCELLED
            else ToolResultStatus.REJECTED
        )
        result = ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            tool_version=call.version,
            capability=definition.capability if definition is not None else None,
            status=result_status,
            error=self._error(code),
            receipt=self._receipt(
                call,
                accepted_at,
                completed_at,
                latency,
                ToolReceiptStatus.FAILED,
                handler_started=handler_started,
            ),
        )
        self._diagnostic(
            ToolDiagnosticStage.POLICY_REJECTED,
            call,
            completed_at,
            capability=definition.capability if definition is not None else None,
            decision=code,
            latency_ms=latency,
        )
        return result

    def _failure(
        self,
        call: ToolCall,
        accepted_at: datetime,
        started: float,
        definition: ToolDefinition,
    ) -> ToolResult:
        completed_at = self._now()
        latency = self._latency(started)
        result = ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            tool_version=call.version,
            capability=definition.capability,
            status=ToolResultStatus.FAILED,
            error=self._error(ToolErrorCode.HANDLER_FAILURE),
            receipt=self._receipt(
                call,
                accepted_at,
                completed_at,
                latency,
                ToolReceiptStatus.FAILED,
                handler_started=True,
            ),
        )
        self._diagnostic(
            ToolDiagnosticStage.FAILED,
            call,
            completed_at,
            capability=definition.capability,
            decision=ToolErrorCode.HANDLER_FAILURE,
            latency_ms=latency,
        )
        return result

    @staticmethod
    def _error(code: ToolErrorCode) -> ToolError:
        categories = {
            ToolErrorCode.TOOL_NOT_FOUND: ToolErrorCategory.LOOKUP,
            ToolErrorCode.UNSUPPORTED_TOOL_VERSION: ToolErrorCategory.LOOKUP,
            ToolErrorCode.INVALID_ARGUMENTS: ToolErrorCategory.VALIDATION,
            ToolErrorCode.CAPABILITY_NOT_ALLOWED: ToolErrorCategory.POLICY,
            ToolErrorCode.MODULE_UNAVAILABLE: ToolErrorCategory.AVAILABILITY,
            ToolErrorCode.MODULE_DISABLED: ToolErrorCategory.AVAILABILITY,
            ToolErrorCode.MISSION_UNAVAILABLE: ToolErrorCategory.AVAILABILITY,
            ToolErrorCode.DATA_UNAVAILABLE: ToolErrorCategory.AVAILABILITY,
            ToolErrorCode.DATA_STALE: ToolErrorCategory.FRESHNESS,
            ToolErrorCode.DATA_RESTRICTED: ToolErrorCategory.POLICY,
            ToolErrorCode.PERMISSION_DENIED: ToolErrorCategory.POLICY,
            ToolErrorCode.CONFIRMATION_REQUIRED: ToolErrorCategory.POLICY,
            ToolErrorCode.CONFIRMATION_INVALID: ToolErrorCategory.POLICY,
            ToolErrorCode.IDEMPOTENCY_REQUIRED: ToolErrorCategory.POLICY,
            ToolErrorCode.DEADLINE_EXCEEDED: ToolErrorCategory.LIFECYCLE,
            ToolErrorCode.CANCELLED: ToolErrorCategory.LIFECYCLE,
            ToolErrorCode.HANDLER_FAILURE: ToolErrorCategory.EXECUTION,
        }
        messages = {
            ToolErrorCode.TOOL_NOT_FOUND: "Tool is not registered.",
            ToolErrorCode.UNSUPPORTED_TOOL_VERSION: "Tool version is not supported.",
            ToolErrorCode.INVALID_ARGUMENTS: "Arguments do not match the registered schema.",
            ToolErrorCode.CAPABILITY_NOT_ALLOWED: "Capability is not allowed by Core policy.",
            ToolErrorCode.MODULE_UNAVAILABLE: "Required Core module is unavailable.",
            ToolErrorCode.MODULE_DISABLED: "Required Core module is disabled.",
            ToolErrorCode.MISSION_UNAVAILABLE: "Required mission state is unavailable.",
            ToolErrorCode.DATA_UNAVAILABLE: "Required data is unavailable.",
            ToolErrorCode.DATA_STALE: "Required data is stale.",
            ToolErrorCode.DATA_RESTRICTED: "Required data is restricted.",
            ToolErrorCode.PERMISSION_DENIED: "Required permission is not granted.",
            ToolErrorCode.CONFIRMATION_REQUIRED: "Explicit confirmation is required.",
            ToolErrorCode.CONFIRMATION_INVALID: "Confirmation is invalid for this call.",
            ToolErrorCode.IDEMPOTENCY_REQUIRED: "An idempotency key is required.",
            ToolErrorCode.DEADLINE_EXCEEDED: "Tool deadline has expired.",
            ToolErrorCode.CANCELLED: "Tool call was cancelled.",
            ToolErrorCode.HANDLER_FAILURE: "Tool handler failed safely.",
        }
        retryable = code in {
            ToolErrorCode.MISSION_UNAVAILABLE,
            ToolErrorCode.DATA_UNAVAILABLE,
            ToolErrorCode.DATA_STALE,
            ToolErrorCode.MODULE_UNAVAILABLE,
        }
        return ToolError(
            code=code,
            category=categories[code],
            message=messages[code],
            retryable=retryable,
        )

    @staticmethod
    def _provenance(output: BaseModel) -> ToolProvenance:
        facts: list[WorldFact] = []  # type: ignore[type-arg]

        def visit(value: object) -> None:
            if isinstance(value, WorldFact):
                facts.append(value)
                return
            if isinstance(value, BaseModel):
                for field_name in type(value).model_fields:
                    visit(getattr(value, field_name))
            elif isinstance(value, (tuple, list)):
                for item in value:
                    visit(item)

        visit(output)
        sources = tuple(dict.fromkeys(fact.source for fact in facts))
        authorities = tuple(dict.fromkeys(fact.authority for fact in facts))
        statuses = tuple(dict.fromkeys(fact.status for fact in facts))
        generations = tuple(
            dict.fromkeys(fact.generation for fact in facts if fact.generation is not None)
        )
        ages = [fact.age_seconds for fact in facts if fact.age_seconds is not None]
        return ToolProvenance(
            sources=cast(tuple[WorldFactSource, ...], sources),
            authorities=cast(tuple[WorldFactAuthority, ...], authorities),
            fact_statuses=cast(tuple[WorldFactStatus, ...], statuses),
            max_age_seconds=max(ages) if ages else None,
            generations=cast(tuple[int | str, ...], generations),
        )

    def _receipt(
        self,
        call: ToolCall,
        accepted_at: datetime,
        completed_at: datetime,
        latency_ms: float,
        status: ToolReceiptStatus,
        *,
        handler_started: bool,
    ) -> ToolReceipt:
        context = call.context
        return ToolReceipt(
            call_id=call.call_id,
            tool_name=call.name,
            tool_version=call.version,
            status=status,
            actor_id=context.actor_id,
            interaction_id=context.interaction_id,
            session_id=context.session_id,
            turn_id=context.turn_id,
            task_id=context.task_id,
            idempotency_key=call.idempotency_key,
            accepted_at=accepted_at,
            completed_at=completed_at,
            latency_ms=latency_ms,
            handler_started=handler_started,
        )

    def _diagnostic(
        self,
        stage: ToolDiagnosticStage,
        call: ToolCall,
        timestamp: datetime,
        *,
        capability: CapabilityId | None = None,
        decision: ToolErrorCode | str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        self._diagnostics.record(
            ToolDiagnosticEvent(
                stage=stage,
                timestamp=timestamp,
                call_id=call.call_id,
                tool_name=call.name,
                tool_version=call.version,
                capability=capability,
                actor_id=call.context.actor_id,
                interaction_id=call.context.interaction_id,
                session_id=call.context.session_id,
                decision=decision,  # type: ignore[arg-type]
                latency_ms=latency_ms,
            )
        )

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Tool Gateway clock must return timezone-aware timestamps")
        return now

    def _latency(self, started: float) -> float:
        return round(max(0.0, (self._monotonic() - started) * 1000), 3)


class NoArguments(ToolSchemaModel):
    schema_identity = "orion.tool.arguments.none.v1"


class PingArguments(ToolSchemaModel):
    schema_identity = "orion.tool.arguments.ping.v1"
    message: str | None = Field(default=None, min_length=1, max_length=200)


class MissionUnitsArguments(ToolSchemaModel):
    schema_identity = "orion.tool.arguments.mission_units.v1"
    coalition: str | None = Field(default=None, min_length=1, max_length=40)
    alive_only: bool = True
    limit: int = Field(default=50, ge=1, le=200)


class GeometryArguments(ToolSchemaModel):
    schema_identity = "orion.tool.arguments.geometry.v1"
    unit_id: str = Field(min_length=1, max_length=200)


class PingOutput(ToolSchemaModel):
    schema_identity = "orion.tool.output.ping.v1"
    pong: str


class OwnshipOutput(ToolSchemaModel):
    schema_identity = "orion.tool.output.ownship.v1"
    snapshot: OwnshipSnapshot


class NavigationOutput(ToolSchemaModel):
    schema_identity = "orion.tool.output.navigation.v1"
    snapshot: OwnshipNavigationSnapshot


class MissionOutput(ToolSchemaModel):
    schema_identity = "orion.tool.output.mission.v1"
    snapshot: MissionIdentitySnapshot


class MissionUnitsOutput(ToolSchemaModel):
    schema_identity = "orion.tool.output.mission_units.v1"
    snapshot: MissionUnitsSnapshot


class GeometryOutput(ToolSchemaModel):
    schema_identity = "orion.tool.output.geometry.v1"
    snapshot: GeometryToUnitSnapshot


class ObservedContactsOutput(ToolSchemaModel):
    schema_identity = "orion.tool.output.observed_contacts.v1"
    snapshot: ObservedContactsSnapshot


def build_tool_gateway(
    *,
    world: WorldModelFacade = world_model,
    modules: RuntimeModuleRegistry = runtime_modules,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.perf_counter,
) -> ToolGateway:
    registry = ToolRegistry()

    def register(
        definition: ToolDefinition,
        input_model: type[InputModel],
        output_model: type[OutputModel],
        handler: ToolHandler[InputModel, OutputModel],
    ) -> None:
        registry.register(definition, input_model, output_model, handler)

    register(
        _definition(
            "orion.test.ping",
            "test.ping",
            PingArguments,
            PingOutput,
            ToolLatencyClass.LOCAL_FAST,
            "Harmless deterministic Core connectivity check.",
        ),
        PingArguments,
        PingOutput,
        lambda arguments, _context: PingOutput(pong=arguments.message or "pong"),
    )
    register(
        _definition(
            "orion.world.ownship.get",
            "world.ownship.read",
            NoArguments,
            OwnshipOutput,
            ToolLatencyClass.LOCAL_FAST,
            "Read the current bounded ownship snapshot.",
        ),
        NoArguments,
        OwnshipOutput,
        lambda _arguments, _context: OwnshipOutput(snapshot=world.ownship()),
    )
    register(
        _definition(
            "orion.world.navigation.get",
            "world.navigation.read",
            NoArguments,
            NavigationOutput,
            ToolLatencyClass.LOCAL_FAST,
            "Read the current bounded ownship navigation snapshot.",
        ),
        NoArguments,
        NavigationOutput,
        lambda _arguments, _context: NavigationOutput(snapshot=world.ownship_navigation()),
    )
    register(
        _definition(
            "orion.world.mission.get",
            "world.mission.read",
            NoArguments,
            MissionOutput,
            ToolLatencyClass.LOCAL_FAST,
            "Read current MissionStore and Mission Bridge identity state.",
        ),
        NoArguments,
        MissionOutput,
        lambda _arguments, _context: MissionOutput(snapshot=world.mission_identity()),
    )
    register(
        _definition(
            "orion.world.units.query",
            "world.units.read",
            MissionUnitsArguments,
            MissionUnitsOutput,
            ToolLatencyClass.LOCAL_QUERY,
            "Read a filtered and bounded mission-truth unit snapshot.",
            mission_required=True,
        ),
        MissionUnitsArguments,
        MissionUnitsOutput,
        lambda arguments, _context: MissionUnitsOutput(
            snapshot=world.mission_units(
                MissionUnitsQuery(
                    coalition=arguments.coalition,
                    alive_only=arguments.alive_only,
                    limit=arguments.limit,
                )
            )
        ),
    )
    register(
        _definition(
            "orion.world.geometry.relative",
            "world.geometry.read",
            GeometryArguments,
            GeometryOutput,
            ToolLatencyClass.LOCAL_QUERY,
            "Derive ownship range, true bearing and vertical separation to a mission unit.",
            mission_required=True,
        ),
        GeometryArguments,
        GeometryOutput,
        lambda arguments, _context: GeometryOutput(
            snapshot=world.geometry_to_unit(GeometryToUnitQuery(unit_id=arguments.unit_id))
        ),
    )
    register(
        _definition(
            "orion.world.contacts.observed",
            "world.contacts.read",
            NoArguments,
            ObservedContactsOutput,
            ToolLatencyClass.LOCAL_FAST,
            "Read observed contacts without substituting omniscient mission truth.",
        ),
        NoArguments,
        ObservedContactsOutput,
        lambda _arguments, _context: ObservedContactsOutput(
            snapshot=world.observed_contacts()
        ),
    )
    return ToolGateway(
        registry=registry,
        world=world,
        modules=modules,
        clock=clock,
        monotonic=monotonic,
    )


def _definition(
    name: str,
    capability: str,
    input_model: type[ToolSchemaModel],
    output_model: type[ToolSchemaModel],
    latency: ToolLatencyClass,
    description: str,
    *,
    mission_required: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1.0",
        capability=CapabilityId(capability),
        description=description,
        input_schema=input_model.schema_identity,
        output_schema=output_model.schema_identity,
        access=ToolAccessMode.READ,
        latency_class=latency,
        side_effect=ToolSideEffect.NONE,
        policy=ToolPolicy(mission_required=mission_required),
    )


tool_gateway = build_tool_gateway()
