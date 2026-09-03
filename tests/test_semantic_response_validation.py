from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from orion.interaction_contracts import (
    CapabilityId,
    ContextReference,
    PresentationMode,
    SemanticFact,
    SemanticFactKind,
    SemanticInputIssue,
    SemanticInputStatus,
    SemanticResponse,
)
from orion.semantic_response_validation import (
    SemanticClaimCategory,
    SemanticConformanceVerdict,
    SemanticValidationError,
    SemanticValidationErrorCode,
    SemanticValidationPolicy,
    parse_semantic_judge_output,
    semantic_request_from_response,
)


INTERACTION_ID = UUID("11111111-1111-1111-1111-111111111111")
SOURCE = ContextReference(
    context_type="world_model",
    reference_id="world-model:ownship",
)
POLICY = SemanticValidationPolicy(
    policy_id="flight.current_aircraft_identity.single_fact.v1",
    semantic_meaning="flight.current_aircraft_identity",
    allowed_known_meaning="Only the current-aircraft identity relationship.",
    allowed_unavailable_meaning="Only that current-aircraft identity is unavailable.",
    prohibited_categories=tuple(SemanticClaimCategory),
)


def _known_response() -> SemanticResponse:
    return SemanticResponse(
        interaction_id=INTERACTION_ID,
        capability=CapabilityId("flight.aircraft_identity"),
        presentation_mode=PresentationMode.NATURALIZE,
        authoritative_facts=(
            SemanticFact(
                key="flight.current_aircraft_identity.raw_dcs_id",
                value="FA-18C_hornet",
                kind=SemanticFactKind.AUTHORITATIVE,
                source=SOURCE,
            ),
        ),
    )


def _unavailable_response() -> SemanticResponse:
    return SemanticResponse(
        interaction_id=INTERACTION_ID,
        capability=CapabilityId("flight.aircraft_identity"),
        presentation_mode=PresentationMode.NATURALIZE,
        unavailable_inputs=(
            SemanticInputIssue(
                key="flight.current_aircraft_identity",
                status=SemanticInputStatus.UNAVAILABLE,
                reason="source_not_connected",
                source=SOURCE,
            ),
        ),
    )


def _request(response: SemanticResponse | None = None):  # noqa: ANN202
    return semantic_request_from_response(
        response or _known_response(),
        policy=POLICY,
        language="ru-RU",
        fact_state="known",
        required_marker="{{aircraft_identity}}",
        candidate_text="Вы находитесь в {{aircraft_identity}}.",
    )


def test_contract_is_tied_to_semantic_response_without_exposing_fact_value() -> None:
    response = _known_response()
    request = _request(response)
    provider_input = request.provider_input()
    assert request.semantic_response_id == response.response_id
    assert request.interaction_id == INTERACTION_ID
    assert "FA-18C_hornet" not in provider_input
    assert "F/A-18C" not in provider_input
    assert "flight.current_aircraft_identity" in provider_input
    assert "candidate_text" in provider_input


def test_known_and_unavailable_core_states_are_not_interchangeable() -> None:
    with pytest.raises(SemanticValidationError) as caught:
        semantic_request_from_response(
            _unavailable_response(),
            policy=POLICY,
            language="ru-RU",
            fact_state="known",
            required_marker="{{aircraft_identity}}",
            candidate_text="Вы в {{aircraft_identity}}.",
        )
    assert caught.value.code is SemanticValidationErrorCode.INVALID_CORE_CONTRACT

    request = semantic_request_from_response(
        _unavailable_response(),
        policy=POLICY,
        language="ru-RU",
        fact_state="unavailable",
        required_marker="{{aircraft_unavailable}}",
        candidate_text="Данные {{aircraft_unavailable}}.",
    )
    assert request.fact_state == "unavailable"
    assert "current-aircraft identity is unavailable" in request.provider_input()


@pytest.mark.parametrize(
    "payload",
    (
        "not-json",
        '{"verdict":"conformant","unsupported_categories":["fuel"]}',
        '{"verdict":"nonconformant","unsupported_categories":[]}',
        '{"verdict":"conformant","unsupported_categories":[],"extra":true}',
        '{"verdict":"nonconformant","unsupported_categories":["unknown"]}',
        '{"conformant":true,"reason":"ok","extra":true}',
        'prefix {"conformant":true,"reason":"ok"}',
        '```yaml\n{"conformant":true,"reason":"ok"}\n```',
    ),
)
def test_malformed_or_inconsistent_judge_output_fails_closed(payload: str) -> None:
    with pytest.raises(SemanticValidationError) as caught:
        parse_semantic_judge_output(
            payload,
            request=_request(),
            provider_id="fake.semantic.judge",
            provider_response_id="response-1",
            latency_ms=5,
            session_reused=True,
        )
    assert caught.value.code is SemanticValidationErrorCode.JUDGE_PROTOCOL


def test_typed_conformant_and_nonconformant_decisions_are_accepted() -> None:
    conformant = parse_semantic_judge_output(
        '{"verdict":"conformant","unsupported_categories":[]}',
        request=_request(),
        provider_id="fake.semantic.judge",
        provider_response_id="response-1",
        latency_ms=5,
        session_reused=True,
    )
    assert conformant.verdict is SemanticConformanceVerdict.CONFORMANT

    rejected = parse_semantic_judge_output(
        '{"verdict":"nonconformant","unsupported_categories":["fuel"]}',
        request=_request(),
        provider_id="fake.semantic.judge",
        provider_response_id="response-2",
        latency_ms=6,
        session_reused=True,
    )
    assert rejected.verdict is SemanticConformanceVerdict.NONCONFORMANT
    assert rejected.unsupported_categories == (SemanticClaimCategory.FUEL,)


def test_current_provider_boolean_json_and_single_fence_are_bounded() -> None:
    conformant = parse_semantic_judge_output(
        '```\n{"conformant":true,"reason":"only allowed meaning"}\n```',
        request=_request(),
        provider_id="yandex.realtime.text",
        provider_response_id="response-3",
        latency_ms=7,
        session_reused=True,
    )
    assert conformant.verdict is SemanticConformanceVerdict.CONFORMANT

    rejected = parse_semantic_judge_output(
        '{"conformant":false,"reason":"unsupported meaning"}',
        request=_request(),
        provider_id="yandex.realtime.text",
        provider_response_id="response-4",
        latency_ms=8,
        session_reused=True,
    )
    assert rejected.verdict is SemanticConformanceVerdict.NONCONFORMANT
    assert rejected.unsupported_categories == (SemanticClaimCategory.UNRELATED_FACT,)


def test_policy_rejects_duplicate_or_empty_semantic_categories() -> None:
    with pytest.raises(ValidationError):
        SemanticValidationPolicy(
            policy_id="test.policy",
            semantic_meaning="test.meaning",
            allowed_known_meaning="known",
            allowed_unavailable_meaning="unavailable",
            prohibited_categories=(),
        )
    with pytest.raises(ValidationError):
        SemanticValidationPolicy(
            policy_id="test.policy",
            semantic_meaning="test.meaning",
            allowed_known_meaning="known",
            allowed_unavailable_meaning="unavailable",
            prohibited_categories=(SemanticClaimCategory.FUEL, SemanticClaimCategory.FUEL),
        )
