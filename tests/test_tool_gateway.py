from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import Field, ValidationError

from orion.interaction_contracts import CapabilityId
from orion.live_telemetry_store import LiveTelemetryStore
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_bridge_ingest import MissionBridgeState
from orion.models import AircraftState, Position, TelemetryEnvelope, VelocityVector
from orion.runtime_modules import OrionRuntimeModule, RuntimeModuleRegistry
from orion.tool_gateway import (
    NoArguments,
    PingArguments,
    PingOutput,
    ToolGateway,
    ToolGatewayDiagnostics,
    ToolRegistry,
    build_tool_gateway,
)
from orion.tool_gateway_contracts import (
    ExecutionContext,
    ToolAccessMode,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolErrorCode,
    ToolFreshnessPolicy,
    ToolLatencyClass,
    ToolPolicy,
    ToolResultStatus,
    ToolSchemaModel,
    ToolSideEffect,
)
from orion.world_model import WorldModelFacade
from orion.world_model_contracts import (
    WorldFact,
    WorldFactAuthority,
    WorldFactReason,
    WorldFactSource,
    WorldFactStatus,
)


NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


@dataclass
class MissionOwner:
    snapshot: MissionSnapshot | None = None

    def get(self) -> MissionSnapshot | None:
        return self.snapshot


@dataclass
class BridgeOwner:
    snapshot: MissionBridgeState = field(default_factory=MissionBridgeState)

    def state(self) -> MissionBridgeState:
        return self.snapshot.model_copy(deep=True)


def telemetry(age_seconds: float = 1) -> LiveTelemetryStore:
    owner = LiveTelemetryStore()
    owner.set(
        TelemetryEnvelope(
            sequence=4,
            state=AircraftState(
                aircraft_type="FA-18C_hornet",
                callsign="Colt 1-1",
                position=Position(
                    latitude=0,
                    longitude=0,
                    altitude_m=1000,
                    altitude_agl_m=600,
                ),
                heading_deg=90,
                true_airspeed_mps=200,
                vertical_speed_mps=1,
                velocity_vector=VelocityVector(x_mps=3, y_mps=1, z_mps=4),
            ),
        ),
        received_at=NOW - timedelta(seconds=age_seconds),
    )
    return owner


def mission(age_seconds: float = 1) -> MissionSnapshot:
    return MissionSnapshot(
        mission_id="mission-ia3",
        name="IA-3 proof",
        theatre="Caucasus",
        mission_time_s=42,
        updated_at=NOW - timedelta(seconds=age_seconds),
        units=[
            MissionUnit(
                unit_id="red-1",
                name="Bandit",
                coalition=Coalition.RED,
                category=UnitCategory.AIRCRAFT,
                position=MissionPosition(latitude=0.1, longitude=0, altitude_m=1500),
                detected=True,
            )
        ],
    )


def world(
    *,
    telemetry_age: float = 1,
    mission_snapshot: MissionSnapshot | None | object = ...,
) -> WorldModelFacade:
    selected = mission() if mission_snapshot is ... else mission_snapshot
    return WorldModelFacade(
        telemetry=telemetry(telemetry_age),
        mission=MissionOwner(selected),  # type: ignore[arg-type]
        mission_bridge=BridgeOwner(),
        clock=lambda: NOW,
    )


def context(
    *capabilities: str,
    permissions: tuple[str, ...] = (),
    **updates: object,
) -> ExecutionContext:
    payload: dict[str, object] = {
        "actor_id": "pilot-1",
        "interaction_id": "interaction-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "task_id": "task-1",
        "provider_id": "future-provider",
        "role": "pilot",
        "domain": "world",
        "allowed_capabilities": tuple(CapabilityId(item) for item in capabilities),
        "permissions": permissions,
    }
    payload.update(updates)
    return ExecutionContext.model_validate(payload)


def call(
    name: str,
    capability: str,
    arguments: dict[str, object] | None = None,
    *,
    execution_context: ExecutionContext | None = None,
    idempotency_key: str | None = None,
    version: str = "1.0",
) -> ToolCall:
    return ToolCall(
        call_id="call-1",
        name=name,
        version=version,
        arguments=ToolArguments.model_validate(arguments or {}),
        context=execution_context or context(capability),
        idempotency_key=idempotency_key,
    )


def gateway(selected_world: WorldModelFacade | None = None) -> ToolGateway:
    return build_tool_gateway(
        world=selected_world or world(),
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
    )


class SampleInput(ToolSchemaModel):
    schema_identity = "orion.test.input.sample.v1"
    value: int = Field(ge=0, le=10)


class SampleOutput(ToolSchemaModel):
    schema_identity = "orion.test.output.sample.v1"
    value: int


class DifferentOutput(ToolSchemaModel):
    schema_identity = "orion.test.output.different.v1"
    text: str


class FactOutput(ToolSchemaModel):
    schema_identity = "orion.test.output.fact.v1"
    fact: WorldFact[int]


def definition(
    *,
    name: str = "orion.test.sample",
    policy: ToolPolicy | None = None,
    access: ToolAccessMode = ToolAccessMode.READ,
    side_effect: ToolSideEffect = ToolSideEffect.NONE,
    output_schema: str = SampleOutput.schema_identity,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1.0",
        capability=CapabilityId("test.sample"),
        description="Deterministic test-only gateway tool.",
        input_schema=SampleInput.schema_identity,
        output_schema=output_schema,
        access=access,
        latency_class=ToolLatencyClass.LOCAL_FAST,
        side_effect=side_effect,
        policy=policy or ToolPolicy(),
    )


def custom_gateway(
    tool_definition: ToolDefinition,
    handler,
    *,
    output_model: type[ToolSchemaModel] = SampleOutput,
    modules: RuntimeModuleRegistry | None = None,
    selected_world: WorldModelFacade | None = None,
    confirmations=None,
) -> ToolGateway:
    registry = ToolRegistry()
    registry.register(tool_definition, SampleInput, output_model, handler)
    return ToolGateway(
        registry=registry,
        world=selected_world or world(),
        modules=modules or RuntimeModuleRegistry(),
        confirmations=confirmations,
        diagnostics=ToolGatewayDiagnostics(),
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
    )


def test_initial_catalog_is_small_stable_versioned_and_read_only() -> None:
    definitions = gateway().definitions()
    assert [(item.name, item.version) for item in definitions] == [
        ("orion.test.ping", "1.0"),
        ("orion.world.contacts.observed", "1.0"),
        ("orion.world.geometry.relative", "1.0"),
        ("orion.world.mission.get", "1.0"),
        ("orion.world.navigation.get", "1.0"),
        ("orion.world.ownship.get", "1.0"),
        ("orion.world.units.query", "1.0"),
    ]
    assert all(item.access is ToolAccessMode.READ for item in definitions)
    assert all(item.side_effect is ToolSideEffect.NONE for item in definitions)


def test_registry_registers_and_rejects_duplicate_or_schema_mismatch() -> None:
    registry = ToolRegistry()
    selected = definition()
    registry.register(selected, SampleInput, SampleOutput, lambda args, _ctx: SampleOutput(value=args.value))
    assert registry.resolve(selected.name, selected.version) is not None
    with pytest.raises(ValueError, match="already registered"):
        registry.register(selected, SampleInput, SampleOutput, lambda args, _ctx: SampleOutput(value=args.value))
    with pytest.raises(ValueError, match="output model"):
        registry.register(
            definition(name="orion.test.mismatch"),
            SampleInput,
            DifferentOutput,
            lambda _args, _ctx: DifferentOutput(text="bad"),
        )


def test_unknown_tool_and_unsupported_version_are_distinct_and_never_execute() -> None:
    selected = gateway()
    unknown = selected.execute(call("orion.test.unknown", "test.ping"))
    unsupported = selected.execute(call("orion.test.ping", "test.ping", version="2.0"))
    assert unknown.error is not None
    assert unknown.error.code is ToolErrorCode.TOOL_NOT_FOUND
    assert unsupported.error is not None
    assert unsupported.error.code is ToolErrorCode.UNSUPPORTED_TOOL_VERSION
    assert not unknown.receipt.handler_started
    assert not unsupported.receipt.handler_started


def test_valid_arguments_execute_and_invalid_or_extra_arguments_do_not() -> None:
    calls: list[int] = []

    def handler(args: SampleInput, _ctx: ExecutionContext) -> SampleOutput:
        calls.append(args.value)
        return SampleOutput(value=args.value)

    selected = custom_gateway(definition(), handler)
    valid = selected.execute(call("orion.test.sample", "test.sample", {"value": 4}))
    invalid = selected.execute(call("orion.test.sample", "test.sample", {"value": 99}))
    extra = selected.execute(
        call("orion.test.sample", "test.sample", {"value": 1, "handler": "other"})
    )
    assert valid.status is ToolResultStatus.COMPLETED
    assert valid.data is not None and valid.data.root == {"value": 4}
    assert invalid.error is not None and invalid.error.code is ToolErrorCode.INVALID_ARGUMENTS
    assert extra.error is not None and extra.error.code is ToolErrorCode.INVALID_ARGUMENTS
    assert calls == [4]


def test_output_validation_failure_and_handler_exception_are_isolated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    wrong = custom_gateway(
        definition(),
        lambda _args, _ctx: DifferentOutput(text="not sample output"),
    ).execute(call("orion.test.sample", "test.sample", {"value": 1}))

    def explode(_args: SampleInput, _ctx: ExecutionContext) -> SampleOutput:
        raise RuntimeError("credential=do-not-expose")

    failed = custom_gateway(definition(), explode).execute(
        call("orion.test.sample", "test.sample", {"value": 1})
    )
    for result in (wrong, failed):
        assert result.status is ToolResultStatus.FAILED
        assert result.error is not None
        assert result.error.code is ToolErrorCode.HANDLER_FAILURE
        assert "credential" not in result.error.message
        assert result.error.retryable is False
    assert "credential=do-not-expose" not in caplog.text


def test_capability_allowlist_is_core_authority_and_checked_before_handler() -> None:
    invoked = False

    def handler(args: SampleInput, _ctx: ExecutionContext) -> SampleOutput:
        nonlocal invoked
        invoked = True
        return SampleOutput(value=args.value)

    selected = custom_gateway(definition(), handler)
    denied = selected.execute(
        call(
            "orion.test.sample",
            "test.sample",
            {"value": 1},
            execution_context=context("world.ownship.read"),
        )
    )
    assert denied.error is not None
    assert denied.error.code is ToolErrorCode.CAPABILITY_NOT_ALLOWED
    assert invoked is False
    assert denied.receipt.handler_started is False


def test_provider_arguments_cannot_expand_capabilities_or_select_a_handler() -> None:
    selected = gateway()
    result = selected.execute(
        call(
            "orion.test.ping",
            "test.ping",
            {"message": "hello", "allowed_capabilities": ["world.units.read"]},
        )
    )
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGUMENTS
    assert result.receipt.handler_started is False


def test_permissions_are_checked_before_handler() -> None:
    selected_definition = definition(
        policy=ToolPolicy(required_permissions=("world.read",))
    )
    selected = custom_gateway(
        selected_definition,
        lambda args, _ctx: SampleOutput(value=args.value),
    )
    denied = selected.execute(call("orion.test.sample", "test.sample", {"value": 1}))
    allowed = selected.execute(
        call(
            "orion.test.sample",
            "test.sample",
            {"value": 1},
            execution_context=context("test.sample", permissions=("world.read",)),
        )
    )
    assert denied.error is not None and denied.error.code is ToolErrorCode.PERMISSION_DENIED
    assert allowed.status is ToolResultStatus.COMPLETED


def test_module_unavailable_and_disabled_are_structured_pre_handler_errors() -> None:
    calls = 0

    def handler(args: SampleInput, _ctx: ExecutionContext) -> SampleOutput:
        nonlocal calls
        calls += 1
        return SampleOutput(value=args.value)

    selected_definition = definition(
        policy=ToolPolicy(required_module="virtual_atc")
    )
    missing_modules = RuntimeModuleRegistry()
    missing = custom_gateway(
        selected_definition,
        handler,
        modules=missing_modules,
    ).execute(call("orion.test.sample", "test.sample", {"value": 1}))

    disabled_modules = RuntimeModuleRegistry()
    disabled_modules.register(OrionRuntimeModule.VIRTUAL_ATC, enabled_by_default=False)
    disabled = custom_gateway(
        selected_definition,
        handler,
        modules=disabled_modules,
    ).execute(call("orion.test.sample", "test.sample", {"value": 1}))
    assert missing.error is not None and missing.error.code is ToolErrorCode.MODULE_UNAVAILABLE
    assert disabled.error is not None and disabled.error.code is ToolErrorCode.MODULE_DISABLED
    assert calls == 0


def test_mission_required_tools_fail_before_handler_when_mission_is_unavailable() -> None:
    selected = gateway(world(mission_snapshot=None))
    result = selected.execute(
        call("orion.world.units.query", "world.units.read", {"limit": 5})
    )
    assert result.error is not None
    assert result.error.code is ToolErrorCode.MISSION_UNAVAILABLE
    assert result.error.retryable is True
    assert result.receipt.handler_started is False


def test_stale_information_is_preserved_and_strict_freshness_can_reject() -> None:
    ownship = gateway(world(telemetry_age=6)).execute(
        call("orion.world.ownship.get", "world.ownship.read")
    )
    assert ownship.status is ToolResultStatus.COMPLETED
    assert ownship.provenance is not None
    assert WorldFactStatus.STALE in ownship.provenance.fact_statuses
    assert "source_status_stale" in ownship.warnings

    strict_definition = ToolDefinition(
        name="orion.test.fresh",
        version="1.0",
        capability=CapabilityId("test.sample"),
        description="Strict freshness test tool.",
        input_schema=SampleInput.schema_identity,
        output_schema=FactOutput.schema_identity,
        access=ToolAccessMode.READ,
        latency_class=ToolLatencyClass.LOCAL_FAST,
        policy=ToolPolicy(freshness=ToolFreshnessPolicy.REQUIRE_FRESH),
    )
    stale_fact = WorldFact[int](
        key="test.value",
        value=1,
        status=WorldFactStatus.STALE,
        source=WorldFactSource.DCS_EXPORT,
        authority=WorldFactAuthority.AUTHORITATIVE,
        reason=WorldFactReason.SOURCE_STALE,
    )
    strict = custom_gateway(
        strict_definition,
        lambda _args, _ctx: FactOutput(fact=stale_fact),
        output_model=FactOutput,
    ).execute(call("orion.test.fresh", "test.sample", {"value": 1}))
    assert strict.error is not None and strict.error.code is ToolErrorCode.DATA_STALE
    assert strict.receipt.handler_started is True


def test_ping_and_world_model_tool_set_return_typed_validated_results() -> None:
    selected = gateway()
    requests: tuple[tuple[str, str, dict[str, object]], ...] = (
        ("orion.test.ping", "test.ping", {"message": "hello"}),
        ("orion.world.ownship.get", "world.ownship.read", {}),
        ("orion.world.navigation.get", "world.navigation.read", {}),
        ("orion.world.mission.get", "world.mission.read", {}),
        ("orion.world.units.query", "world.units.read", {"coalition": "red", "limit": 1}),
        ("orion.world.geometry.relative", "world.geometry.read", {"unit_id": "red-1"}),
    )
    for name, capability, arguments in requests:
        result = selected.execute(call(name, capability, arguments))
        assert result.status is ToolResultStatus.COMPLETED
        assert result.data is not None
        assert result.output_schema is not None
        assert result.error is None
    geometry = selected.execute(
        call(
            "orion.world.geometry.relative",
            "world.geometry.read",
            {"unit_id": "red-1"},
        )
    )
    assert geometry.data is not None
    value = geometry.data.root["snapshot"]
    assert isinstance(value, dict)
    geometry_fact = value["geometry"]
    assert isinstance(geometry_fact, dict)
    assert geometry_fact["authority"] == "derived"


def test_observed_contacts_remain_restricted_and_never_leak_mission_truth() -> None:
    result = gateway().execute(
        call("orion.world.contacts.observed", "world.contacts.read")
    )
    assert result.status is ToolResultStatus.COMPLETED
    assert result.provenance is not None
    assert result.provenance.fact_statuses == (WorldFactStatus.RESTRICTED,)
    assert "source_status_restricted" in result.warnings
    assert result.data is not None
    snapshot = result.data.root["snapshot"]
    assert isinstance(snapshot, dict)
    contacts = snapshot["contacts"]
    assert isinstance(contacts, dict)
    assert contacts["status"] == "restricted"
    assert contacts["value"] is None
    assert "Bandit" not in result.model_dump_json()


def test_deadline_and_cancellation_are_rejected_before_handler() -> None:
    selected = gateway()
    expired = selected.execute(
        call(
            "orion.test.ping",
            "test.ping",
            execution_context=context("test.ping", deadline=NOW),
        )
    )
    cancelled = selected.execute(
        call(
            "orion.test.ping",
            "test.ping",
            execution_context=context(
                "test.ping",
                cancelled=True,
                cancellation_id="cancel-1",
            ),
        )
    )
    assert expired.error is not None and expired.error.code is ToolErrorCode.DEADLINE_EXCEEDED
    assert cancelled.error is not None and cancelled.error.code is ToolErrorCode.CANCELLED
    assert cancelled.status is ToolResultStatus.CANCELLED
    assert not expired.receipt.handler_started and not cancelled.receipt.handler_started


def test_correlation_actor_and_session_context_are_preserved_in_receipt() -> None:
    result = gateway().execute(call("orion.test.ping", "test.ping"))
    assert result.call_id == "call-1"
    assert result.receipt.actor_id == "pilot-1"
    assert result.receipt.interaction_id == "interaction-1"
    assert result.receipt.session_id == "session-1"
    assert result.receipt.turn_id == "turn-1"
    assert result.receipt.task_id == "task-1"
    assert result.receipt.handler_started
    assert result.receipt.latency_ms == 0


def test_diagnostics_are_bounded_and_never_record_arguments_results_or_credentials() -> None:
    selected = gateway()
    selected.execute(
        call(
            "orion.test.ping",
            "test.ping",
            {"message": "credential-value-must-not-appear"},
        )
    )
    events = selected.diagnostic_snapshot()
    assert [event.stage.value for event in events] == [
        "received",
        "handler_started",
        "completed",
    ]
    serialized = "".join(event.model_dump_json() for event in events)
    assert "credential-value" not in serialized
    assert "arguments" not in serialized
    assert "result" not in serialized


def test_future_write_definition_requires_confirmation_and_idempotency_without_side_effect() -> None:
    invoked = False

    def handler(args: SampleInput, _ctx: ExecutionContext) -> SampleOutput:
        nonlocal invoked
        invoked = True
        return SampleOutput(value=args.value)

    write_definition = definition(
        access=ToolAccessMode.WRITE,
        side_effect=ToolSideEffect.CORE_STATE,
        policy=ToolPolicy(confirmation_required=True, idempotency_required=True),
    )
    selected = custom_gateway(write_definition, handler)
    no_confirmation = selected.execute(
        call("orion.test.sample", "test.sample", {"value": 1})
    )
    invalid_confirmation = selected.execute(
        call(
            "orion.test.sample",
            "test.sample",
            {"value": 1},
            execution_context=context("test.sample", confirmation_id="confirmation-1"),
        )
    )
    assert no_confirmation.error is not None
    assert no_confirmation.error.code is ToolErrorCode.CONFIRMATION_REQUIRED
    assert invalid_confirmation.error is not None
    assert invalid_confirmation.error.code is ToolErrorCode.CONFIRMATION_INVALID
    assert invoked is False


def test_future_write_idempotency_gate_runs_after_bound_confirmation() -> None:
    invoked = False

    class AllowTestConfirmation:
        def validate(self, confirmation_id, selected_call, selected_definition) -> bool:
            assert confirmation_id == "confirmation-1"
            assert selected_call.context.actor_id == "pilot-1"
            assert selected_definition.name == "orion.test.sample"
            return True

    def handler(args: SampleInput, _ctx: ExecutionContext) -> SampleOutput:
        nonlocal invoked
        invoked = True
        return SampleOutput(value=args.value)

    write_definition = definition(
        access=ToolAccessMode.WRITE,
        side_effect=ToolSideEffect.CORE_STATE,
        policy=ToolPolicy(confirmation_required=True, idempotency_required=True),
    )
    selected = custom_gateway(
        write_definition,
        handler,
        confirmations=AllowTestConfirmation(),
    )
    missing_key = selected.execute(
        call(
            "orion.test.sample",
            "test.sample",
            {"value": 1},
            execution_context=context("test.sample", confirmation_id="confirmation-1"),
        )
    )
    assert missing_key.error is not None
    assert missing_key.error.code is ToolErrorCode.IDEMPOTENCY_REQUIRED
    assert missing_key.error.retryable is False
    assert missing_key.receipt.handler_started is False
    assert invoked is False


def test_write_contract_rejects_missing_side_effect_and_read_confirmation() -> None:
    with pytest.raises(ValidationError):
        definition(access=ToolAccessMode.WRITE)
    with pytest.raises(ValidationError):
        definition(policy=ToolPolicy(confirmation_required=True))


def test_gateway_does_not_mutate_world_model_state() -> None:
    owner = MissionOwner(mission())
    selected_world = WorldModelFacade(
        telemetry=telemetry(),
        mission=owner,
        mission_bridge=BridgeOwner(),
        clock=lambda: NOW,
    )
    before = owner.snapshot.model_dump_json() if owner.snapshot is not None else ""
    gateway(selected_world).execute(
        call("orion.world.units.query", "world.units.read", {"limit": 1})
    )
    assert owner.snapshot is not None
    assert owner.snapshot.model_dump_json() == before


def test_tool_contracts_and_gateway_are_provider_transport_neutral() -> None:
    package = Path(__file__).parents[1] / "orion"
    forbidden = ("yandex", "qwen", "openai", "srs", "mcp", "realtime_tools")
    for filename in ("tool_gateway_contracts.py", "tool_gateway.py"):
        tree = ast.parse((package / filename).read_text(encoding="utf-8"))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ] + [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(token in name.casefold() for name in imports for token in forbidden)


def test_contract_serialization_is_stable_and_has_no_secret_authority_fields() -> None:
    selected_call = call("orion.test.ping", "test.ping", {"message": "hello"})
    restored = ToolCall.model_validate_json(selected_call.model_dump_json())
    assert restored == selected_call
    forbidden = {"api_key", "authorization", "headers", "provider_payload", "password"}
    assert forbidden.isdisjoint(ToolCall.model_fields)
    assert forbidden.isdisjoint(ExecutionContext.model_fields)


def test_tool_arguments_are_bounded() -> None:
    with pytest.raises(ValidationError):
        ToolArguments.model_validate({f"field_{index}": index for index in range(65)})
