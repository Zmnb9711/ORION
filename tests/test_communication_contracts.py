from uuid import UUID

import pytest
from pydantic import ValidationError

from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
    OperationalSemanticUnit,
    OutputClassification,
    ProtectedOperationalFragment,
    ProtectedProvenance,
    ProtectedValue,
    ProtectedValueKind,
    ResponseCompositionPlan,
    UntrustedConversationalEnvelope,
)
from orion.interaction_contracts import ContextReference
from orion.world_model_contracts import WorldFactAuthority


INTERACTION_ID = UUID("12345678-1234-5678-1234-567812345678")


def operational_unit() -> OperationalSemanticUnit:
    return OperationalSemanticUnit(
        unit_type="navigation.heading",
        semantic_meaning="navigation.heading_assignment",
        domain=CommunicationDomain.NAVIGATION,
        priority=CommunicationPriority.IMPORTANT,
        status="issued",
        polarity="positive",
        protected_values=(
            ProtectedValue(
                key="ownship.heading_deg",
                kind=ProtectedValueKind.HEADING,
                value=137,
                unit="deg",
            ),
        ),
        provenance=(
            ProtectedProvenance(
                source=ContextReference(
                    context_type="tool_result",
                    reference_id="ownship-call-1",
                ),
                authority=WorldFactAuthority.AUTHORITATIVE,
                generation=7,
                domain_origin=CommunicationDomain.NAVIGATION,
            ),
        ),
    )


def test_approved_profile_domain_priority_and_output_ids_are_stable() -> None:
    assert [item.value for item in CommunicationProfileId] == [
        "ICAO",
        "FAA_US",
        "NATO_MILITARY",
        "FAP_RUSSIAN_ATC",
    ]
    assert CommunicationDomain.AWACS_GCI.value == "awacs_gci"
    assert [item.value for item in CommunicationPriority] == [
        "routine",
        "important",
        "urgent",
        "immediate",
    ]
    assert OutputClassification.OPERATIONAL_PROTECTED.value == "operational_protected"


def test_profile_domain_and_languages_remain_separate_without_fake_snapshot() -> None:
    context = CommunicationContext(
        profile_id=CommunicationProfileId.NATO_MILITARY,
        domain=CommunicationDomain.AWACS_GCI,
        input_language="ru-RU",
        operational_language="en-US",
    )
    assert context.profile_id is CommunicationProfileId.NATO_MILITARY
    assert context.domain is CommunicationDomain.AWACS_GCI
    assert context.input_language == "ru-RU"
    assert context.operational_language == "en-US"
    assert context.phraseology_snapshot_id is None
    assert context.phraseology_version is None


def test_operational_unit_and_protected_values_are_immutable_and_unique() -> None:
    unit = operational_unit()
    with pytest.raises(ValidationError):
        unit.priority = CommunicationPriority.ROUTINE  # type: ignore[misc]
    with pytest.raises(ValidationError, match="must be unique"):
        OperationalSemanticUnit(
            unit_type="navigation.heading",
            semantic_meaning="navigation.heading_assignment",
            domain=CommunicationDomain.NAVIGATION,
            priority=CommunicationPriority.IMPORTANT,
            protected_values=(unit.protected_values[0], unit.protected_values[0]),
        )


def test_composition_boundary_keeps_untrusted_envelope_separate_from_core_fragment() -> (
    None
):
    fragment = ProtectedOperationalFragment(
        text="Fly heading one three seven.",
        semantic_unit=operational_unit(),
        renderer_version="synthetic-test-renderer-v1",
    )
    envelope = UntrustedConversationalEnvelope(text="Understood.")
    plan = ResponseCompositionPlan(
        interaction_id=INTERACTION_ID,
        communication=CommunicationContext(
            profile_id=CommunicationProfileId.ICAO,
            domain=CommunicationDomain.NAVIGATION,
        ),
        priority=CommunicationPriority.IMPORTANT,
        envelope=envelope,
        protected_fragments=(fragment,),
    )
    assert plan.envelope is not None and plan.envelope.droppable
    assert not plan.envelope.authoritative
    assert plan.protected_fragments[0].rendered_by_core
    with pytest.raises(ValidationError):
        plan.protected_fragments[0].text = "Qwen rewrite"  # type: ignore[misc]


def test_immediate_composition_requires_complete_envelope_suppression() -> None:
    context = CommunicationContext(profile_id=CommunicationProfileId.ICAO)
    with pytest.raises(ValidationError, match="must suppress"):
        ResponseCompositionPlan(
            interaction_id=INTERACTION_ID,
            communication=context,
            priority=CommunicationPriority.IMMEDIATE,
        )
    plan = ResponseCompositionPlan(
        interaction_id=INTERACTION_ID,
        communication=context,
        priority=CommunicationPriority.IMMEDIATE,
        suppress_conversational_envelope=True,
    )
    assert plan.envelope is None
