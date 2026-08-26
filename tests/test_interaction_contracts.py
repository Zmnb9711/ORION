from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError

from orion.interaction_contracts import (
    CapabilityId,
    ContextReference,
    InteractionRequest,
    PresentationMode,
    RouteDecision,
    RouteMode,
    SemanticFact,
    SemanticFactKind,
    SemanticInputIssue,
    SemanticInputStatus,
    SemanticResponse,
)


class _CapabilityEnvelope(BaseModel):
    capability: CapabilityId


def _authoritative_fact() -> SemanticFact:
    return SemanticFact(
        key="flight.true_airspeed",
        value=251,
        kind=SemanticFactKind.AUTHORITATIVE,
        unit="kt",
        source=ContextReference(
            context_type="flight",
            reference_id="telemetry-generation-42",
        ),
    )


def _derived_fact() -> SemanticFact:
    return SemanticFact(
        key="navigation.range_to_tanker",
        value=18.4,
        kind=SemanticFactKind.DERIVED,
        unit="nm",
    )


def test_capability_id_is_a_stable_string_identifier() -> None:
    capability = CapabilityId("flight.current_state")
    assert isinstance(capability, str)
    assert capability == "flight.current_state"
    assert {capability: "handler"}[capability] == "handler"


@pytest.mark.parametrize(
    "value",
    ("", "   ", "Flight.CurrentState", "flight current", ".flight", "flight."),
)
def test_capability_id_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        CapabilityId(value)


def test_capability_id_keeps_plain_string_json_wire_value() -> None:
    envelope = _CapabilityEnvelope(capability=CapabilityId("atc.request_landing"))
    assert envelope.model_dump(mode="json") == {
        "capability": "atc.request_landing"
    }
    assert _CapabilityEnvelope.model_validate_json(envelope.model_dump_json()) == envelope


def test_interaction_request_minimal_shape_is_provider_neutral() -> None:
    request = InteractionRequest(text="What is my speed?")
    assert isinstance(request.interaction_id, UUID)
    assert request.session_id is None
    assert request.turn_id is None
    assert request.context_references == ()
    assert request.allowed_capabilities == ()
    assert request.created_at.tzinfo is not None


def test_interaction_request_round_trip_preserves_typed_fields() -> None:
    request = InteractionRequest(
        interaction_id=uuid4(),
        session_id="session-7",
        turn_id="turn_003",
        text="Request landing",
        role_hint="pilot",
        domain_hint="atc",
        context_references=(
            ContextReference(context_type="radio", reference_id="comm1-current"),
        ),
        allowed_capabilities=(CapabilityId("atc.request_landing"),),
        created_at=datetime(2026, 8, 26, 12, 30, tzinfo=UTC),
    )
    restored = InteractionRequest.model_validate_json(request.model_dump_json())
    assert restored == request
    assert isinstance(restored.allowed_capabilities[0], CapabilityId)


def test_interaction_request_has_no_provider_or_payload_fields() -> None:
    fields = set(InteractionRequest.model_fields)
    forbidden = {
        "provider_payload",
        "audio",
        "pcm",
        "opus",
        "base64",
        "credentials",
        "authorization",
        "headers",
        "metadata",
        "flight_context",
        "mission_context",
        "conversation_history",
    }
    assert fields.isdisjoint(forbidden)
    with pytest.raises(ValidationError):
        InteractionRequest.model_validate(
            {"text": "hello", "provider_payload": {"type": "yandex-event"}}
        )


def test_interaction_request_rejects_blank_text_and_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        InteractionRequest(text="  ")
    with pytest.raises(ValidationError):
        InteractionRequest(text="hello", created_at=datetime(2026, 8, 26))


@pytest.mark.parametrize(
    "route",
    (RouteMode.FAST, RouteMode.PLANNER, RouteMode.UNAVAILABLE),
)
def test_route_decision_supports_approved_modes(route: RouteMode) -> None:
    decision = RouteDecision(
        interaction_id=uuid4(),
        route=route,
        reason="routing.contract_test",
        confidence=0.75,
        selected_capability=CapabilityId("flight.current_state"),
    )
    assert decision.route is route
    assert decision.model_dump(mode="json")["route"] == route.value


def test_route_decision_rejects_invalid_route() -> None:
    payload = {
        "interaction_id": str(uuid4()),
        "route": "yandex",
        "reason": "unsupported_route",
    }
    with pytest.raises(ValidationError):
        RouteDecision.model_validate(payload)


def test_route_decision_rejects_unsafe_free_form_reason() -> None:
    with pytest.raises(ValidationError):
        RouteDecision(
            interaction_id=uuid4(),
            route=RouteMode.FAST,
            reason="provider selected this",
        )


@pytest.mark.parametrize("confidence", (-0.01, 1.01))
def test_route_decision_confidence_is_bounded(confidence: float) -> None:
    with pytest.raises(ValidationError):
        RouteDecision(
            interaction_id=uuid4(),
            route=RouteMode.FAST,
            reason="fast_path",
            confidence=confidence,
        )


def test_route_decision_selected_capability_belongs_to_candidates() -> None:
    with pytest.raises(ValidationError):
        RouteDecision(
            interaction_id=uuid4(),
            route=RouteMode.FAST,
            reason="capability_selected",
            selected_capability=CapabilityId("flight.current_state"),
            candidate_capabilities=(CapabilityId("radio.current_state"),),
        )


def test_semantic_response_separates_all_semantic_categories() -> None:
    issue = SemanticInputIssue(
        key="weather.current",
        status=SemanticInputStatus.UNAVAILABLE,
        reason="weather_source_unavailable",
    )
    response = SemanticResponse(
        interaction_id=uuid4(),
        capability=CapabilityId("mission.option_comparison"),
        authoritative_facts=(_authoritative_fact(),),
        derived_results=(_derived_fact(),),
        recommendation="Proceed to the tanker if the route remains clear.",
        assumptions=("Current fuel flow remains stable.",),
        unavailable_inputs=(issue,),
        warnings=("Weather data is unavailable.",),
    )
    assert response.authoritative_facts[0].kind is SemanticFactKind.AUTHORITATIVE
    assert response.derived_results[0].kind is SemanticFactKind.DERIVED
    assert response.recommendation is not None
    assert response.assumptions
    assert response.unavailable_inputs[0].status is SemanticInputStatus.UNAVAILABLE
    assert response.warnings


def test_naturalize_mode_accepts_semantics_and_forbids_verbatim_text() -> None:
    response = SemanticResponse(
        interaction_id=uuid4(),
        authoritative_facts=(_authoritative_fact(),),
    )
    assert response.presentation_mode is PresentationMode.NATURALIZE
    with pytest.raises(ValidationError):
        SemanticResponse(
            interaction_id=uuid4(),
            presentation_mode=PresentationMode.NATURALIZE,
            recommendation="Return to base.",
            verbatim_text="Return to base.",
        )


def test_verbatim_mode_requires_finalized_text() -> None:
    response = SemanticResponse(
        interaction_id=uuid4(),
        presentation_mode=PresentationMode.VERBATIM,
        verbatim_text="Орион, полоса занята, уходите на второй круг.",
    )
    assert response.verbatim_text is not None
    with pytest.raises(ValidationError):
        SemanticResponse(
            interaction_id=uuid4(),
            presentation_mode=PresentationMode.VERBATIM,
            warnings=("No finalized speech was supplied.",),
        )


def test_semantic_response_round_trip_preserves_enums_and_identifiers() -> None:
    response = SemanticResponse(
        interaction_id=uuid4(),
        capability=CapabilityId("flight.current_state"),
        authoritative_facts=(_authoritative_fact(),),
        unavailable_inputs=(
            SemanticInputIssue(
                key="location.airfield",
                status=SemanticInputStatus.UNKNOWN,
                reason="authoritative_airfield_unknown",
            ),
        ),
    )
    restored = SemanticResponse.model_validate_json(response.model_dump_json())
    assert restored == response
    assert isinstance(restored.capability, CapabilityId)
    assert restored.authoritative_facts[0].kind is SemanticFactKind.AUTHORITATIVE


def test_semantic_response_rejects_empty_or_misclassified_results() -> None:
    with pytest.raises(ValidationError):
        SemanticResponse(interaction_id=uuid4())
    with pytest.raises(ValidationError):
        SemanticResponse(
            interaction_id=uuid4(),
            authoritative_facts=(_derived_fact(),),
        )
    with pytest.raises(ValidationError):
        SemanticResponse(
            interaction_id=uuid4(),
            authoritative_facts=(_authoritative_fact(),),
            derived_results=(
                SemanticFact(
                    key="flight.true_airspeed",
                    value=488,
                    kind=SemanticFactKind.DERIVED,
                    unit="km/h",
                ),
            ),
        )
    with pytest.raises(ValidationError):
        SemanticResponse(
            interaction_id=uuid4(),
            authoritative_facts=(_authoritative_fact(),),
            unavailable_inputs=(
                SemanticInputIssue(
                    key="flight.true_airspeed",
                    status=SemanticInputStatus.UNKNOWN,
                    reason="value_unknown",
                ),
            ),
        )


def test_contract_repr_hides_user_and_semantic_content_and_has_no_secret_fields() -> None:
    request = InteractionRequest(text="private spoken content")
    response = SemanticResponse(
        interaction_id=request.interaction_id,
        authoritative_facts=(_authoritative_fact(),),
        recommendation="private recommendation",
    )
    assert "private spoken content" not in repr(request)
    assert "private recommendation" not in repr(response)
    forbidden_fragments = ("secret", "password", "token", "authorization", "headers")
    for model in (
        ContextReference,
        InteractionRequest,
        RouteDecision,
        SemanticFact,
        SemanticInputIssue,
        SemanticResponse,
    ):
        assert all(
            fragment not in field.casefold()
            for field in model.model_fields
            for fragment in forbidden_fragments
        )


def test_contract_module_has_no_runtime_or_provider_imports() -> None:
    module_path = Path(__file__).parents[1] / "orion" / "interaction_contracts.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = (
        "orion.yandex_realtime",
        "orion.qwen_",
        "orion.srs_",
        "orion.dcs_",
        "orion.realtime_live_core",
    )
    assert not any(name.startswith(forbidden) for name in imported)


def test_only_approved_architecture_boundaries_import_ia0_contracts() -> None:
    package = Path(__file__).parents[1] / "orion"
    consumers = []
    for path in package.glob("*.py"):
        if path.name == "interaction_contracts.py":
            continue
        if "interaction_contracts" in path.read_text(encoding="utf-8"):
            consumers.append(path.name)
    assert sorted(consumers) == [
        "planner.py",
        "planner_contracts.py",
        "realtime_test_evidence.py",
        "tool_gateway.py",
        "tool_gateway_contracts.py",
        "yandex_presentation.py",
    ]
