from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from orion.interaction_contracts import (
    CapabilityId,
    ContextReference,
    InteractionRequest,
    SemanticFact,
    SemanticFactKind,
    SemanticInputIssue,
    SemanticInputStatus,
    SemanticResponse,
)
from orion.live_telemetry_store import LiveTelemetryStore
from orion.mission import MissionSnapshot
from orion.mission_bridge_ingest import MissionBridgeState
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.planner import (
    PlannerCancellationToken,
    PlannerDiagnostics,
    PlannerProvider,
    PlannerRun,
    PlannerTaskRunner,
    PlannerTaskStateMachine,
)
from orion.planner_contracts import (
    PlannerDiagnosticStage,
    PlannerError,
    PlannerErrorCategory,
    PlannerErrorCode,
    PlannerEvent,
    PlannerExecutionPolicy,
    PlannerFailedEvent,
    PlannerFinalResponseEvent,
    PlannerProviderRequest,
    PlannerStartedEvent,
    PlannerTaskStatus,
    PlannerTimedOutEvent,
    PlannerToolCallsEvent,
    PlannerToolRequest,
    PlannerUsage,
    ProviderRetryPolicy,
)
from orion.tool_gateway import ToolGateway, build_tool_gateway
from orion.tool_gateway_contracts import ToolArguments, ToolDiagnosticStage, ToolResult
from orion.world_model import WorldModelFacade
from orion.world_model_contracts import WorldFactAuthority, WorldFactStatus


NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
INTERACTION_ID = UUID("12345678-1234-5678-1234-567812345678")


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


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def telemetry(*, age_seconds: float = 1, available: bool = True) -> LiveTelemetryStore:
    store = LiveTelemetryStore()
    if available:
        store.set(
            TelemetryEnvelope(
                sequence=7,
                state=AircraftState(
                    aircraft_type="FA-18C_hornet",
                    callsign="Colt 1-1",
                    position=Position(latitude=42.1, longitude=41.2, altitude_m=2100),
                    heading_deg=137,
                    true_airspeed_mps=145,
                ),
            ),
            received_at=NOW - timedelta(seconds=age_seconds),
        )
    return store


def world(*, age_seconds: float = 1, telemetry_available: bool = True) -> WorldModelFacade:
    return WorldModelFacade(
        telemetry=telemetry(age_seconds=age_seconds, available=telemetry_available),
        mission=MissionOwner(),
        mission_bridge=BridgeOwner(),
        clock=lambda: NOW,
    )


def gateway(*, age_seconds: float = 1, telemetry_available: bool = True) -> ToolGateway:
    return build_tool_gateway(
        world=world(age_seconds=age_seconds, telemetry_available=telemetry_available),
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
    )


def interaction(*capabilities: str, text: str = "Where am I and what is my heading?") -> InteractionRequest:
    return InteractionRequest(
        interaction_id=INTERACTION_ID,
        session_id="session-1",
        turn_id="turn-1",
        text=text,
        role_hint="pilot",
        domain_hint="flight",
        context_references=(ContextReference(context_type="flight", reference_id="current"),),
        allowed_capabilities=tuple(CapabilityId(item) for item in capabilities),
        created_at=NOW,
    )


def policy(
    *,
    deadline: datetime | None = None,
    max_tool_rounds: int = 4,
) -> PlannerExecutionPolicy:
    return PlannerExecutionPolicy(
        actor_id="pilot-1",
        provider_id="fake",
        permissions=("world.read",),
        core_instructions=("Use only Core tool results for authoritative facts.",),
        deadline=deadline or NOW + timedelta(minutes=1),
        max_tool_rounds=max_tool_rounds,
        provider_retry=ProviderRetryPolicy(max_attempts=2),
    )


def tool_request(
    call_id: str,
    name: str = "orion.test.ping",
    arguments: dict[str, object] | None = None,
) -> PlannerToolRequest:
    return PlannerToolRequest(
        call_id=call_id,
        name=name,
        version="1.0",
        arguments=ToolArguments.model_validate(arguments or {}),
    )


def recommendation_response(
    *,
    interaction_id: UUID = INTERACTION_ID,
    capability: str | None = None,
    text: str = "Planner response complete.",
) -> SemanticResponse:
    return SemanticResponse(
        interaction_id=interaction_id,
        capability=CapabilityId(capability) if capability else None,
        recommendation=text,
    )


Step = PlannerEvent | Callable[["ScriptedRun"], PlannerEvent]


class ScriptedRun:
    def __init__(
        self,
        steps: list[Step],
        *,
        on_next: Callable[[], None] | None = None,
        on_continue: Callable[[], None] | None = None,
    ) -> None:
        self.steps = steps
        self.continuations: list[tuple[ToolResult, ...]] = []
        self.cancelled = False
        self.on_next = on_next
        self.on_continue = on_continue

    def next_event(
        self,
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken,
    ) -> PlannerEvent:
        assert deadline.tzinfo is not None
        assert isinstance(cancellation, PlannerCancellationToken)
        if self.on_next is not None:
            callback, self.on_next = self.on_next, None
            callback()
        if not self.steps:
            raise RuntimeError("script exhausted credential=must-not-leak")
        step = self.steps.pop(0)
        return step(self) if callable(step) else step

    def continue_with_tool_results(self, results: tuple[ToolResult, ...]) -> None:
        self.continuations.append(results)
        if self.on_continue is not None:
            callback, self.on_continue = self.on_continue, None
            callback()

    def cancel(self) -> None:
        self.cancelled = True


class FakeProvider:
    provider_id = "fake"

    def __init__(self, run: ScriptedRun, *, fail_start: bool = False) -> None:
        self.run = run
        self.fail_start = fail_start
        self.requests: list[PlannerProviderRequest] = []

    def start(self, request: PlannerProviderRequest) -> PlannerRun:
        self.requests.append(request)
        if self.fail_start:
            raise RuntimeError("authorization=must-not-leak")
        return self.run


def runner(
    selected_gateway: ToolGateway | None = None,
    *,
    clock: MutableClock | None = None,
    diagnostics: PlannerDiagnostics | None = None,
) -> PlannerTaskRunner:
    selected_clock = clock or MutableClock()
    return PlannerTaskRunner(
        gateway=selected_gateway or gateway(),
        diagnostics=diagnostics,
        clock=selected_clock,
        monotonic=lambda: 20.0,
        task_id_factory=lambda: "planner-task-1",
    )


def test_contracts_are_immutable_serializable_bounded_and_forbid_extra_fields() -> None:
    request = interaction("test.ping")
    selected_policy = policy()
    restored = PlannerExecutionPolicy.model_validate_json(selected_policy.model_dump_json())
    assert restored == selected_policy
    with pytest.raises(ValidationError):
        PlannerExecutionPolicy.model_validate({**selected_policy.model_dump(), "provider_payload": {}})
    with pytest.raises(ValidationError):
        selected_policy.max_tool_rounds = 8  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ProviderRetryPolicy(max_attempts=4)
    assert "mission" not in PlannerProviderRequest.model_fields


def test_provider_request_is_task_scoped_and_catalog_is_capability_filtered() -> None:
    run = ScriptedRun(
        [PlannerFinalResponseEvent(event_id="final-1", response=recommendation_response())]
    )
    provider = FakeProvider(run)
    result = runner().execute(interaction("test.ping"), provider, policy())
    assert result.task.status is PlannerTaskStatus.COMPLETED
    provider_request = provider.requests[0]
    assert [item.name for item in provider_request.available_tools] == ["orion.test.ping"]
    serialized = provider_request.model_dump_json()
    for forbidden in ("MissionStore", "telemetry_history", "cockpit_dump", "transcript"):
        assert forbidden not in serialized


def test_created_running_completed_immediate_response() -> None:
    provider = FakeProvider(
        ScriptedRun(
            [
                PlannerStartedEvent(event_id="start-1"),
                PlannerFinalResponseEvent(event_id="final-1", response=recommendation_response()),
            ]
        )
    )
    selected = runner()
    result = selected.execute(interaction(), provider, policy())
    assert result.task.status is PlannerTaskStatus.COMPLETED
    assert result.response is not None
    assert result.task.final_response_id == result.response.response_id
    assert [event.stage for event in selected.diagnostic_snapshot()] == [
        PlannerDiagnosticStage.TASK_CREATED,
        PlannerDiagnosticStage.PROVIDER_STARTED,
        PlannerDiagnosticStage.COMPLETED,
    ]


def test_one_tool_round_correlates_call_result_receipt_and_continuation() -> None:
    run = ScriptedRun(
        [
            PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-1"),)),
            PlannerFinalResponseEvent(event_id="final-1", response=recommendation_response()),
        ]
    )
    result = runner().execute(interaction("test.ping"), FakeProvider(run), policy())
    assert result.task.status is PlannerTaskStatus.COMPLETED
    assert result.task.tool_rounds == 1
    assert result.task.requested_call_ids == ("call-1",)
    assert result.task.completed_tool_receipts[0].call_id == "call-1"
    assert run.continuations[0][0].call_id == "call-1"
    assert run.continuations[0][0].receipt.task_id == "planner-task-1"


def test_multiple_sequential_tool_rounds_are_supported() -> None:
    def second(run: ScriptedRun) -> PlannerEvent:
        assert run.continuations[-1][0].call_id == "call-a"
        return PlannerToolCallsEvent(event_id="tools-2", calls=(tool_request("call-b"),))

    def final(run: ScriptedRun) -> PlannerEvent:
        assert run.continuations[-1][0].call_id == "call-b"
        return PlannerFinalResponseEvent(event_id="final-1", response=recommendation_response())

    run = ScriptedRun(
        [PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-a"),)), second, final]
    )
    result = runner().execute(interaction("test.ping"), FakeProvider(run), policy())
    assert result.task.status is PlannerTaskStatus.COMPLETED
    assert result.task.tool_rounds == 2
    assert result.task.requested_call_ids == ("call-a", "call-b")


def test_multiple_tool_calls_in_one_round_are_correlated() -> None:
    calls = (tool_request("call-a"), tool_request("call-b", arguments={"message": "two"}))
    run = ScriptedRun(
        [
            PlannerToolCallsEvent(event_id="tools-1", calls=calls),
            PlannerFinalResponseEvent(event_id="final-1", response=recommendation_response()),
        ]
    )
    result = runner().execute(interaction("test.ping"), FakeProvider(run), policy())
    assert result.task.status is PlannerTaskStatus.COMPLETED
    assert result.task.requested_call_ids == ("call-a", "call-b")
    assert [item.call_id for item in run.continuations[0]] == ["call-a", "call-b"]


def test_duplicate_tool_event_reuses_recorded_result_without_second_execution() -> None:
    selected_gateway = gateway()
    repeated = PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-1"),))
    run = ScriptedRun(
        [repeated, repeated, PlannerFinalResponseEvent(event_id="final-1", response=recommendation_response())]
    )
    result = runner(selected_gateway).execute(interaction("test.ping"), FakeProvider(run), policy())
    assert result.task.status is PlannerTaskStatus.COMPLETED
    assert result.task.requested_call_ids == ("call-1",)
    assert len(result.task.completed_tool_receipts) == 1
    handler_starts = [
        event
        for event in selected_gateway.diagnostic_snapshot()
        if event.stage is ToolDiagnosticStage.HANDLER_STARTED
    ]
    assert len(handler_starts) == 1
    assert run.continuations[0][0] is run.continuations[1][0]
    assert result.task.tool_rounds == 1


def test_duplicate_event_id_with_changed_payload_is_rejected_before_execution() -> None:
    selected_gateway = gateway()
    run = ScriptedRun(
        [
            PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-1"),)),
            PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-2"),)),
        ]
    )
    result = runner(selected_gateway).execute(interaction("test.ping"), FakeProvider(run), policy())
    assert result.error is not None
    assert result.error.code is PlannerErrorCode.INVALID_PROVIDER_EVENT
    assert result.task.requested_call_ids == ("call-1",)


def test_duplicate_call_id_with_different_request_fails_without_second_execution() -> None:
    selected_gateway = gateway()
    run = ScriptedRun(
        [
            PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-1"),)),
            PlannerToolCallsEvent(
                event_id="tools-2",
                calls=(tool_request("call-1", arguments={"message": "changed"}),),
            ),
        ]
    )
    result = runner(selected_gateway).execute(interaction("test.ping"), FakeProvider(run), policy())
    assert result.error is not None
    assert result.error.code is PlannerErrorCode.INVALID_TOOL_REQUEST
    assert len(result.task.completed_tool_receipts) == 1


def test_capability_denial_and_unknown_tool_are_propagated_as_tool_rejection() -> None:
    for requested in (
        tool_request("call-1", "orion.world.ownship.get"),
        tool_request("call-1", "orion.test.not_registered"),
    ):
        run = ScriptedRun([PlannerToolCallsEvent(event_id="tools-1", calls=(requested,))])
        result = runner().execute(interaction("test.ping"), FakeProvider(run), policy())
        assert result.error is not None
        assert result.error.code is PlannerErrorCode.TOOL_CALL_REJECTED
        assert result.task.completed_tool_receipts[0].handler_started is False


def test_restricted_stale_and_unavailable_tool_results_reach_provider_unchanged() -> None:
    scenarios = (
        (gateway(), "orion.world.contacts.observed", "world.contacts.read", WorldFactStatus.RESTRICTED),
        (gateway(age_seconds=8), "orion.world.ownship.get", "world.ownship.read", WorldFactStatus.STALE),
        (gateway(telemetry_available=False), "orion.world.ownship.get", "world.ownship.read", WorldFactStatus.UNAVAILABLE),
    )
    for selected_gateway, tool_name, capability, expected_status in scenarios:
        run = ScriptedRun(
            [
                PlannerToolCallsEvent(
                    event_id="tools-1",
                    calls=(tool_request("call-1", tool_name),),
                ),
                PlannerFinalResponseEvent(event_id="final-1", response=recommendation_response()),
            ]
        )
        result = runner(selected_gateway).execute(interaction(capability), FakeProvider(run), policy())
        assert result.task.status is PlannerTaskStatus.COMPLETED
        provenance = run.continuations[0][0].provenance
        assert provenance is not None
        assert expected_status in provenance.fact_statuses


def test_tool_round_limit_fails_closed_without_second_round_execution() -> None:
    run = ScriptedRun(
        [
            PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-a"),)),
            PlannerToolCallsEvent(event_id="tools-2", calls=(tool_request("call-b"),)),
        ]
    )
    result = runner().execute(
        interaction("test.ping"),
        FakeProvider(run),
        policy(max_tool_rounds=1),
    )
    assert result.error is not None
    assert result.error.code is PlannerErrorCode.TOOL_ROUND_LIMIT_EXCEEDED
    assert result.task.requested_call_ids == ("call-a",)


def test_deadline_before_provider_start_times_out_without_starting_provider() -> None:
    provider = FakeProvider(ScriptedRun([]))
    result = runner().execute(interaction(), provider, policy(deadline=NOW))
    assert result.task.status is PlannerTaskStatus.TIMED_OUT
    assert result.error is not None and result.error.code is PlannerErrorCode.DEADLINE_EXCEEDED
    assert provider.requests == []


def test_deadline_after_provider_wait_prevents_new_tool_execution_and_cancels_run() -> None:
    clock = MutableClock()
    run = ScriptedRun(
        [PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-1"),))],
        on_next=lambda: clock.advance(61),
    )
    result = runner(clock=clock).execute(
        interaction("test.ping"),
        FakeProvider(run),
        policy(deadline=NOW + timedelta(seconds=60)),
    )
    assert result.task.status is PlannerTaskStatus.TIMED_OUT
    assert result.task.completed_tool_receipts == ()
    assert run.cancelled


def test_cancellation_before_start_between_rounds_and_during_provider_wait() -> None:
    before = PlannerCancellationToken()
    before.cancel()
    before_provider = FakeProvider(ScriptedRun([]))
    before_result = runner().execute(interaction(), before_provider, policy(), cancellation=before)
    assert before_result.task.status is PlannerTaskStatus.CANCELLED
    assert before_provider.requests == []

    between = PlannerCancellationToken()
    between_run = ScriptedRun(
        [PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-1"),))],
        on_continue=between.cancel,
    )
    between_result = runner().execute(
        interaction("test.ping"), FakeProvider(between_run), policy(), cancellation=between
    )
    assert between_result.task.status is PlannerTaskStatus.CANCELLED
    assert between_run.cancelled

    during = PlannerCancellationToken()
    during_run = ScriptedRun(
        [PlannerFinalResponseEvent(event_id="final-1", response=recommendation_response())],
        on_next=during.cancel,
    )
    during_result = runner().execute(
        interaction(), FakeProvider(during_run), policy(), cancellation=during
    )
    assert during_result.task.status is PlannerTaskStatus.CANCELLED
    assert during_run.cancelled


def test_provider_failure_timeout_and_raw_exception_are_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unavailable = PlannerError(
        code=PlannerErrorCode.PROVIDER_UNAVAILABLE,
        category=PlannerErrorCategory.PROVIDER,
        message="Provider unavailable.",
        retryable=True,
    )
    failed = runner().execute(
        interaction(),
        FakeProvider(ScriptedRun([PlannerFailedEvent(event_id="fail-1", error=unavailable)])),
        policy(),
    )
    timed_out = runner().execute(
        interaction(),
        FakeProvider(ScriptedRun([PlannerTimedOutEvent(event_id="timeout-1")])),
        policy(),
    )
    exploded = runner().execute(
        interaction(), FakeProvider(ScriptedRun([]), fail_start=True), policy()
    )
    assert failed.error is not None and failed.error.code is PlannerErrorCode.PROVIDER_UNAVAILABLE
    assert timed_out.error is not None and timed_out.error.code is PlannerErrorCode.PROVIDER_TIMEOUT
    assert exploded.error is not None and exploded.error.code is PlannerErrorCode.INTERNAL_PLANNER_ERROR
    assert "authorization=must-not-leak" not in caplog.text
    assert all(error.error is not None for error in (failed, timed_out, exploded))


def test_tool_gateway_exception_is_contained_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    selected_gateway = gateway()

    def explode(_call: object) -> ToolResult:
        raise RuntimeError("authorization=gateway-secret")

    monkeypatch.setattr(selected_gateway, "execute", explode)
    run = ScriptedRun(
        [PlannerToolCallsEvent(event_id="tools-1", calls=(tool_request("call-1"),))]
    )
    result = runner(selected_gateway).execute(
        interaction("test.ping"), FakeProvider(run), policy()
    )
    assert result.error is not None
    assert result.error.code is PlannerErrorCode.INTERNAL_PLANNER_ERROR
    assert "gateway-secret" not in result.model_dump_json()
    assert "gateway-secret" not in caplog.text


def test_invalid_provider_event_is_rejected_without_exposing_payload() -> None:
    run = ScriptedRun([cast(PlannerEvent, {"hidden_reasoning": "credential=secret"})])
    selected = runner()
    result = selected.execute(interaction(), FakeProvider(run), policy())
    assert result.error is not None
    assert result.error.code is PlannerErrorCode.INVALID_PROVIDER_EVENT
    assert "hidden_reasoning" not in result.model_dump_json()
    assert "credential=secret" not in "".join(
        event.model_dump_json() for event in selected.diagnostic_snapshot()
    )


def test_final_response_wrong_interaction_or_capability_is_rejected() -> None:
    wrong_id = recommendation_response(
        interaction_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    )
    wrong_capability = recommendation_response(capability="world.units.read")
    for response in (wrong_id, wrong_capability):
        result = runner().execute(
            interaction("test.ping"),
            FakeProvider(
                ScriptedRun([PlannerFinalResponseEvent(event_id="final-1", response=response)])
            ),
            policy(),
        )
        assert result.error is not None
        assert result.error.code is PlannerErrorCode.INVALID_FINAL_RESPONSE


def test_authoritative_fact_requires_completed_authoritative_tool_provenance() -> None:
    unsupported = SemanticResponse(
        interaction_id=INTERACTION_ID,
        authoritative_facts=(
            SemanticFact(
                key="flight.heading_deg",
                value=137,
                kind=SemanticFactKind.AUTHORITATIVE,
            ),
        ),
    )
    result = runner().execute(
        interaction(),
        FakeProvider(
            ScriptedRun([PlannerFinalResponseEvent(event_id="final-1", response=unsupported)])
        ),
        policy(),
    )
    assert result.error is not None
    assert result.error.code is PlannerErrorCode.INVALID_FINAL_RESPONSE


def test_restricted_tool_cannot_prove_an_authoritative_fact() -> None:
    response = SemanticResponse(
        interaction_id=INTERACTION_ID,
        authoritative_facts=(
            SemanticFact(
                key="contacts.count",
                value=0,
                kind=SemanticFactKind.AUTHORITATIVE,
                source=ContextReference(context_type="tool_result", reference_id="contacts-1"),
            ),
        ),
    )
    run = ScriptedRun(
        [
            PlannerToolCallsEvent(
                event_id="tools-1",
                calls=(tool_request("contacts-1", "orion.world.contacts.observed"),),
            ),
            PlannerFinalResponseEvent(event_id="final-1", response=response),
        ]
    )
    result = runner().execute(
        interaction("world.contacts.read"), FakeProvider(run), policy()
    )
    assert result.error is not None
    assert result.error.code is PlannerErrorCode.INVALID_FINAL_RESPONSE


def test_end_to_end_fake_provider_gateway_world_model_to_semantic_response() -> None:
    def final_from_tool(run: ScriptedRun) -> PlannerEvent:
        tool_result = run.continuations[-1][0]
        assert tool_result.status.value == "completed"
        assert tool_result.provenance is not None
        assert WorldFactAuthority.AUTHORITATIVE in tool_result.provenance.authorities
        assert tool_result.data is not None
        snapshot = tool_result.data.root["snapshot"]
        assert isinstance(snapshot, dict)
        heading = snapshot["heading_deg"]
        assert isinstance(heading, dict)
        return PlannerFinalResponseEvent(
            event_id="final-1",
            response=SemanticResponse(
                interaction_id=INTERACTION_ID,
                capability=CapabilityId("world.ownship.read"),
                authoritative_facts=(
                    SemanticFact(
                        key="flight.heading_deg",
                        value=cast(int, heading["value"]),
                        kind=SemanticFactKind.AUTHORITATIVE,
                        unit="deg_true",
                        source=ContextReference(
                            context_type="tool_result",
                            reference_id=tool_result.call_id,
                        ),
                    ),
                ),
                unavailable_inputs=(
                    SemanticInputIssue(
                        key="navigation.route",
                        status=SemanticInputStatus.UNAVAILABLE,
                        reason="source_not_implemented",
                    ),
                ),
                recommendation="Ownship heading is 137 degrees true.",
            ),
        )

    run = ScriptedRun(
        [
            PlannerToolCallsEvent(
                event_id="tools-1",
                calls=(tool_request("ownship-1", "orion.world.ownship.get"),),
            ),
            final_from_tool,
        ]
    )
    result = runner().execute(
        interaction("world.ownship.read"), FakeProvider(run), policy()
    )
    assert result.task.status is PlannerTaskStatus.COMPLETED
    assert result.response is not None
    assert result.response.authoritative_facts[0].value == 137
    assert result.response.unavailable_inputs[0].key == "navigation.route"


def test_usage_metadata_is_optional_bounded_and_merged() -> None:
    started_usage = PlannerUsage(
        provider_request_ids=("provider-request-1",), input_tokens=10, provider_attempts=1
    )
    final_usage = PlannerUsage(
        provider_request_ids=("provider-request-2",), output_tokens=5, provider_latency_ms=20
    )
    run = ScriptedRun(
        [
            PlannerStartedEvent(event_id="start-1", usage=started_usage),
            PlannerFinalResponseEvent(
                event_id="final-1", response=recommendation_response(), usage=final_usage
            ),
        ]
    )
    result = runner().execute(interaction(), FakeProvider(run), policy())
    assert result.task.usage is not None
    assert result.task.usage.provider_request_ids == (
        "provider-request-1",
        "provider-request-2",
    )
    assert result.task.usage.input_tokens == 10
    assert result.task.usage.output_tokens == 5


def test_illegal_state_transition_is_rejected() -> None:
    state = PlannerTaskStateMachine()
    with pytest.raises(ValueError, match="Illegal planner transition"):
        state.transition(PlannerTaskStatus.COMPLETED)
    state.transition(PlannerTaskStatus.RUNNING)
    state.transition(PlannerTaskStatus.COMPLETED)
    with pytest.raises(ValueError, match="Illegal planner transition"):
        state.transition(PlannerTaskStatus.RUNNING)


def test_diagnostics_are_bounded_correlated_and_privacy_safe() -> None:
    diagnostics = PlannerDiagnostics(max_events=4)
    run = ScriptedRun(
        [
            PlannerToolCallsEvent(
                event_id="tools-1",
                calls=(tool_request("call-1", arguments={"message": "credential-secret"}),),
            ),
            PlannerFinalResponseEvent(
                event_id="final-1",
                response=recommendation_response(text="hidden reasoning must not be recorded"),
            ),
        ]
    )
    selected = runner(diagnostics=diagnostics)
    selected.execute(interaction("test.ping"), FakeProvider(run), policy())
    events = selected.diagnostic_snapshot()
    assert len(events) == 4
    assert all(event.planner_task_id == "planner-task-1" for event in events)
    serialized = "".join(event.model_dump_json() for event in events)
    for forbidden in ("credential-secret", "hidden reasoning", "arguments", "response"):
        assert forbidden not in serialized


def test_production_planner_modules_are_provider_transport_neutral() -> None:
    package = Path(__file__).parents[1] / "orion"
    forbidden = ("yandex", "qwen", "openai", "anthropic", "srs", "speechkit", "mcp")
    for filename in ("planner_contracts.py", "planner.py"):
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


def test_provider_protocol_structurally_accepts_deterministic_fake() -> None:
    provider: PlannerProvider = FakeProvider(
        ScriptedRun(
            [PlannerFinalResponseEvent(event_id="final-1", response=recommendation_response())]
        )
    )
    result = runner().execute(interaction(), provider, policy())
    assert result.task.status is PlannerTaskStatus.COMPLETED
