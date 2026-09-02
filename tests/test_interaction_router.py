from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationProfileId,
)
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
from orion.interaction_router import (
    InteractionRoute,
    InteractionRouter,
    KnownContractReasonCode,
    KnownContractRoute,
    RouteReasonCode,
    RouterExecutionStatus,
)
from orion.interaction_router_api import router as api_router
from orion.interaction_router_api import InteractionSubmission
from orion.live_telemetry_store import LiveTelemetryStore
from orion.mission import MissionSnapshot
from orion.mission_bridge_ingest import MissionBridgeState
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.planner import PlannerCancellationToken, PlannerTaskRunner
from orion.planner_contracts import (
    PlannerErrorCode,
    PlannerEvent,
    PlannerFinalResponseEvent,
    PlannerProviderRequest,
    PlannerToolCallsEvent,
    PlannerToolRequest,
)
from orion.tool_gateway import build_tool_gateway
from orion.tool_gateway_contracts import ToolArguments, ToolResult
from orion.world_model import WorldModelFacade
from orion.yandex_qwen_planner import QWEN_PROVIDER_ID


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
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


class OwnshipRun:
    def __init__(
        self,
        request: PlannerProviderRequest,
        *,
        heading: int = 137,
        include_position: bool = True,
        claim_unsourced_unavailable_position: bool = False,
    ) -> None:
        self.request = request
        self.heading = heading
        self.include_position = include_position
        self.claim_unsourced_unavailable_position = claim_unsourced_unavailable_position
        self.results: tuple[ToolResult, ...] = ()
        self.step = 0
        self.cancelled = False

    def next_event(
        self,
        *,
        deadline: datetime,
        cancellation: PlannerCancellationToken,
    ) -> PlannerEvent:
        assert deadline == self.request.deadline
        assert not cancellation.cancelled
        self.step += 1
        if self.step == 1:
            return PlannerToolCallsEvent(
                event_id="ownship-tools",
                calls=(
                    PlannerToolRequest(
                        call_id="ownship-call",
                        name="orion.world.ownship.get",
                        version="1.0",
                        arguments=ToolArguments(root={}),
                    ),
                ),
            )
        tool = self.results[0]
        facts = [
            SemanticFact(
                key="ownship.heading_deg",
                value=self.heading,
                kind=SemanticFactKind.AUTHORITATIVE,
                unit="deg",
                source=ContextReference(
                    context_type="tool_result",
                    reference_id=tool.call_id,
                ),
            )
        ]
        if self.include_position:
            facts.extend(
                (
                    SemanticFact(
                        key="ownship.position.latitude",
                        value=42.1,
                        kind=SemanticFactKind.AUTHORITATIVE,
                        source=ContextReference(
                            context_type="tool_result",
                            reference_id=tool.call_id,
                        ),
                    ),
                    SemanticFact(
                        key="ownship.position.longitude",
                        value=41.2,
                        kind=SemanticFactKind.AUTHORITATIVE,
                        source=ContextReference(
                            context_type="tool_result",
                            reference_id=tool.call_id,
                        ),
                    ),
                )
            )
        return PlannerFinalResponseEvent(
            event_id="ownship-final",
            response=SemanticResponse(
                interaction_id=self.request.interaction.interaction_id,
                capability=CapabilityId("world.ownship.read"),
                authoritative_facts=tuple(facts),
                unavailable_inputs=(
                    (
                        SemanticInputIssue(
                            key="ownship.position",
                            status=SemanticInputStatus.UNAVAILABLE,
                            reason="provider_claimed_unavailable",
                        ),
                    )
                    if self.claim_unsourced_unavailable_position
                    else ()
                ),
                recommendation="Current ownship situation is available.",
            ),
        )

    def continue_with_tool_results(self, results: tuple[ToolResult, ...]) -> None:
        self.results = results

    def cancel(self) -> None:
        self.cancelled = True


class OwnshipProvider:
    provider_id = QWEN_PROVIDER_ID

    def __init__(
        self,
        *,
        heading: int = 137,
        include_position: bool = True,
        claim_unsourced_unavailable_position: bool = False,
    ) -> None:
        self.heading = heading
        self.include_position = include_position
        self.claim_unsourced_unavailable_position = claim_unsourced_unavailable_position
        self.requests: list[PlannerProviderRequest] = []

    def start(self, request: PlannerProviderRequest) -> OwnshipRun:
        self.requests.append(request)
        return OwnshipRun(
            request,
            heading=self.heading,
            include_position=self.include_position,
            claim_unsourced_unavailable_position=self.claim_unsourced_unavailable_position,
        )


def gateway():  # type: ignore[no-untyped-def]
    telemetry = LiveTelemetryStore()
    telemetry.set(
        TelemetryEnvelope(
            sequence=1,
            state=AircraftState(
                aircraft_type="FA-18C_hornet",
                callsign="Colt 1-1",
                position=Position(latitude=42.1, longitude=41.2, altitude_m=2100),
                heading_deg=137,
                true_airspeed_mps=145,
            ),
        ),
        received_at=NOW - timedelta(seconds=1),
    )
    world = WorldModelFacade(
        telemetry=telemetry,
        mission=MissionOwner(),
        mission_bridge=BridgeOwner(),
        clock=lambda: NOW,
    )
    return build_tool_gateway(world=world, clock=lambda: NOW, monotonic=lambda: 10.0)


def build_router(provider: OwnshipProvider) -> InteractionRouter:
    planner = PlannerTaskRunner(
        gateway=gateway(),
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
        task_id_factory=lambda: f"planner-{len(provider.requests) + 1}",
    )
    return InteractionRouter(
        planner=planner,
        provider_factory=lambda: provider,
        clock=lambda: NOW,
    )


def request(text: str, *, interaction_id: UUID = INTERACTION_ID) -> InteractionRequest:
    return InteractionRequest(
        interaction_id=interaction_id,
        text=text,
        allowed_capabilities=(
            CapabilityId("world.units.read"),
            CapabilityId("test.ping"),
        ),
        created_at=NOW,
    )


def context(
    profile: CommunicationProfileId = CommunicationProfileId.ICAO,
) -> CommunicationContext:
    return CommunicationContext(
        profile_id=profile,
        domain=CommunicationDomain.NAVIGATION,
        input_language="en-US",
    )


def test_direct_health_bypasses_provider_and_unsupported_fails_closed() -> None:
    provider = OwnshipProvider()
    selected = build_router(provider)
    direct = selected.execute(
        request("health check"), context(), deadline=NOW + timedelta(seconds=30)
    )
    assert direct.status is RouterExecutionStatus.COMPLETED
    assert direct.decision.route is InteractionRoute.DIRECT_HEALTH_OR_TEST
    assert direct.response is not None and direct.response.capability == "test.ping"
    assert not provider.requests

    unsupported = selected.execute(
        request("Launch every weapon", interaction_id=uuid4()),
        context(),
        deadline=NOW + timedelta(seconds=30),
    )
    assert unsupported.status is RouterExecutionStatus.UNSUPPORTED
    assert unsupported.error_code is RouteReasonCode.UNSUPPORTED_INTERACTION_CLASS
    assert not provider.requests


def test_pure_ru_and_en_takeoff_route_before_qwen_without_provider_calls() -> None:
    provider = OwnshipProvider()
    selected = build_router(provider)

    for utterance in (
        "Разрешите взлёт.",
        "Можно взлетать?",
        "Запрашиваю разрешение на взлёт.",
        "Request takeoff.",
        "Ready for takeoff.",
    ):
        decision = selected.route_known_contract(request(utterance), context())
        assert decision.route is KnownContractRoute.DETERMINISTIC_KNOWN_CONTRACT
        assert (
            decision.reason_code
            is KnownContractReasonCode.PURE_TAKEOFF_CLEARANCE_REQUEST
        )
        assert decision.contract == "takeoff_clearance_request"
        assert decision.contract_matched is decision.pure is True
        assert decision.qwen_required is False
        assert decision.qwen_formulation_required is False
        assert decision.requested_capability == "atc.takeoff.clearance.request"

    assert provider.requests == []

    routes_by_profile = {
        selected.route_known_contract(
            request("Разрешите взлёт.", interaction_id=uuid4()),
            context(profile),
        ).route
        for profile in CommunicationProfileId
    }
    assert routes_by_profile == {KnownContractRoute.DETERMINISTIC_KNOWN_CONTRACT}


def test_pure_ru_and_en_atc_status_route_before_qwen_without_provider_calls() -> None:
    provider = OwnshipProvider()
    selected = build_router(provider)

    for utterance in (
        "Какой диспетчер сейчас управляет моим полётом?",
        "  КТО СЕЙЧАС УПРАВЛЯЕТ МОИМ ПОЛЕТОМ!!!  ",
        "Who currently controls my flight?",
        "WHICH CONTROLLER CURRENTLY CONTROLS MY FLIGHT.",
    ):
        decision = selected.route_known_contract(request(utterance), context())
        assert decision.route is KnownContractRoute.DETERMINISTIC_KNOWN_CONTRACT
        assert decision.reason_code is KnownContractReasonCode.PURE_ATC_STATUS_QUERY
        assert decision.contract == "atc_status_query"
        assert decision.contract_matched is decision.pure is True
        assert decision.qwen_required is False
        assert decision.qwen_formulation_required is False
        assert decision.requested_capability == "atc.status.current_flight_controller"

    assert provider.requests == []


def test_pure_ru_and_en_aircraft_identity_route_before_qwen_without_provider_calls() -> None:
    provider = OwnshipProvider()
    selected = build_router(provider)

    for utterance in (
        "В каком самолёте я нахожусь?",
        "На каком самолете я сейчас нахожусь!",
        "Какой у меня самолёт?",
        "What aircraft am I in?",
        "WHAT AIRCRAFT AM I FLYING!",
        "Which aircraft am I flying?",
    ):
        decision = selected.route_known_contract(request(utterance), context())
        assert decision.route is KnownContractRoute.DETERMINISTIC_KNOWN_CONTRACT
        assert (
            decision.reason_code
            is KnownContractReasonCode.PURE_AIRCRAFT_IDENTITY_QUERY
        )
        assert decision.contract == "aircraft_identity_query"
        assert decision.contract_matched is decision.pure is True
        assert decision.qwen_required is False
        assert decision.qwen_formulation_required is True
        assert decision.requested_capability == "flight.aircraft_identity"

    assert provider.requests == []

    routes_by_profile = {
        selected.route_known_contract(
            request("В каком самолёте я нахожусь?", interaction_id=uuid4()),
            context(profile),
        ).route
        for profile in CommunicationProfileId
    }
    assert routes_by_profile == {KnownContractRoute.DETERMINISTIC_KNOWN_CONTRACT}


def test_mixed_free_unknown_and_ambiguous_inputs_preserve_qwen_fallback() -> None:
    provider = OwnshipProvider()
    selected = build_router(provider)
    inputs = (
        "Добрый день! Разрешите взлёт.",
        "Разрешите взлёт и скажите частоту.",
        "После взлёта какая будет частота?",
        "Расскажи про взлёт.",
        "Почему мне не разрешили взлёт?",
        "Если разрешат взлёт, что делать дальше?",
        "Какие сегодня новости перед взлётом?",
        "Как дела?",
        "unknown text",
        "Tower, hello, request takeoff and report departure frequency.",
        "Takeoff.",
        "Добрый день! Кто сейчас управляет моим полётом?",
        "Кто сейчас управляет моим полётом и какая частота?",
        "Он спросил: кто сейчас управляет моим полётом?",
        "Я не спрашиваю, кто сейчас управляет моим полётом",
        "Кто диспетчер?",
        "Какой диспетчер?",
        "Кто управляет?",
        "Привет, в каком самолёте я нахожусь?",
        "В каком самолёте я нахожусь и как включить TACAN?",
        "Он спросил: в каком самолёте я нахожусь?",
        "Если бы я был в F-16, какой это был бы самолёт?",
        "Какой самолёт летит справа?",
        "Что это за самолёт на радаре?",
        "Что ты знаешь про F/A-18?",
        "Я в F/A-18 или F-16?",
        "Какой это самолёт?",
    )

    for utterance in inputs:
        decision = selected.route_known_contract(request(utterance), context())
        assert decision.route is KnownContractRoute.EXISTING_QWEN_FALLBACK
        assert decision.contract is None
        assert decision.contract_matched is decision.pure is False
        assert decision.qwen_required is True
        assert decision.qwen_formulation_required is False
        assert decision.requested_capability is None

    assert provider.requests == []

def test_controlled_slice_uses_qwen_planner_exact_ia3_tool_and_ia2_values() -> None:
    provider = OwnshipProvider()
    selected = build_router(provider)
    result = selected.execute(
        request("What is my current heading and position?"),
        context(),
        deadline=NOW + timedelta(seconds=30),
    )
    assert result.status is RouterExecutionStatus.COMPLETED
    assert result.decision.route is InteractionRoute.PLANNER_CONTROLLED
    assert result.response is not None
    assert [fact.key for fact in result.response.authoritative_facts] == [
        "ownship.heading_deg",
        "ownship.position.latitude",
        "ownship.position.longitude",
    ]
    provider_request = provider.requests[0]
    assert provider_request.allowed_capabilities == (
        CapabilityId("world.ownship.read"),
    )
    assert [item.name for item in provider_request.available_tools] == [
        "orion.world.ownship.get"
    ]
    instructions = " ".join(provider_request.core_instructions)
    assert "ownship.heading_deg" in instructions
    assert "ownship.position.latitude" in instructions
    assert "ownship.position.longitude" in instructions
    assert "do not return altitude" in instructions
    assert "derived_results must be empty" in instructions
    assert "no fact key may appear in more than one semantic section" in instructions
    assert result.planner_task is not None
    assert result.planner_task.requested_call_ids == ("ownship-call",)


def test_exact_binding_rejects_provider_heading_mutation() -> None:
    provider = OwnshipProvider(heading=173)
    result = build_router(provider).execute(
        request("What is my current heading and position?"),
        context(),
        deadline=NOW + timedelta(seconds=30),
    )
    assert result.status is RouterExecutionStatus.FAILED
    assert result.error_code is PlannerErrorCode.INVALID_FINAL_RESPONSE


def test_controlled_slice_rejects_semantically_incomplete_heading_only_response() -> (
    None
):
    provider = OwnshipProvider(include_position=False)
    result = build_router(provider).execute(
        request("What is my current heading and position?"),
        context(),
        deadline=NOW + timedelta(seconds=30),
    )
    assert result.status is RouterExecutionStatus.FAILED
    assert result.error_code is PlannerErrorCode.INVALID_FINAL_RESPONSE


def test_controlled_slice_rejects_unsourced_provider_unavailable_claim() -> None:
    provider = OwnshipProvider(
        include_position=False,
        claim_unsourced_unavailable_position=True,
    )
    result = build_router(provider).execute(
        request("What is my current heading and position?"),
        context(),
        deadline=NOW + timedelta(seconds=30),
    )
    assert result.status is RouterExecutionStatus.FAILED
    assert result.error_code is PlannerErrorCode.INVALID_FINAL_RESPONSE


def test_profile_is_orthogonal_to_route_tools_and_authority() -> None:
    provider = OwnshipProvider()
    selected = build_router(provider)
    results = [
        selected.execute(
            request("What is my current heading and position?", interaction_id=uuid4()),
            context(profile),
            deadline=NOW + timedelta(seconds=30),
        )
        for profile in CommunicationProfileId
    ]
    assert all(item.status is RouterExecutionStatus.COMPLETED for item in results)
    assert {item.decision.route for item in results} == {
        InteractionRoute.PLANNER_CONTROLLED
    }
    assert {request.allowed_capabilities for request in provider.requests} == {
        (CapabilityId("world.ownship.read"),)
    }
    assert {
        tuple(tool.name for tool in request.available_tools)
        for request in provider.requests
    } == {("orion.world.ownship.get",)}


def test_replay_returns_recorded_result_and_conflict_never_executes_tool_again() -> (
    None
):
    provider = OwnshipProvider()
    selected = build_router(provider)
    original = request("What is my current heading and position?")
    first = selected.execute(original, context(), deadline=NOW + timedelta(seconds=30))
    replay = selected.execute(original, context(), deadline=NOW + timedelta(seconds=50))
    assert replay is first
    assert len(provider.requests) == 1

    conflict = selected.execute(
        request(
            "Current heading and coordinates please", interaction_id=INTERACTION_ID
        ),
        context(),
        deadline=NOW + timedelta(seconds=30),
    )
    assert conflict.status is RouterExecutionStatus.DENIED
    assert conflict.error_code is RouteReasonCode.REPLAY_CONFLICT
    assert len(provider.requests) == 1


def test_deadline_cancellation_and_diagnostics_are_bounded_and_private() -> None:
    provider = OwnshipProvider()
    selected = build_router(provider)
    expired = selected.execute(
        request("What is my current heading and position?"),
        context(),
        deadline=NOW,
    )
    assert expired.status is RouterExecutionStatus.TIMED_OUT
    cancelled_token = PlannerCancellationToken()
    cancelled_token.cancel()
    cancelled = selected.execute(
        request("What is my current heading and position?", interaction_id=uuid4()),
        context(),
        deadline=NOW + timedelta(seconds=30),
        cancellation=cancelled_token,
    )
    assert cancelled.status is RouterExecutionStatus.CANCELLED
    evidence = repr(selected.diagnostic_snapshot())
    assert "What is my" not in evidence
    assert "Authorization" not in evidence


def test_http_boundary_constructs_core_owned_request_without_exposing_capability_policy(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    provider = OwnshipProvider()
    selected = build_router(provider)
    monkeypatch.setattr("orion.interaction_router_api.interaction_router", selected)
    app = FastAPI()
    app.include_router(api_router)
    response = TestClient(app).post(
        "/v1/interactions",
        json={
            "interaction_id": str(INTERACTION_ID),
            "text": "health check",
            "communication_profile": "FAP_RUSSIAN_ATC",
            "domain": "general",
            "input_language": "ru-RU",
        },
    )
    assert response.status_code == 200
    body = cast(dict[str, object], response.json())
    assert body["status"] == "completed"
    assert not provider.requests


def test_router_module_is_provider_neutral_and_api_does_not_accept_authority_fields() -> (
    None
):
    source = (Path(__file__).parents[1] / "orion" / "interaction_router.py").read_text(
        encoding="utf-8"
    )
    assert "yandex" not in source.casefold()
    assert "windows_credentials" not in source
    assert "api_key" not in source
    fields = set(InteractionSubmission.model_fields)
    assert not fields.intersection(
        {"allowed_capabilities", "permissions", "provider_id", "tools", "api_key"}
    )
