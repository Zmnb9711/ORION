from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from orion.airport_surface import RunwayAvailability, RunwayState
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.airport_tower_runtime import AirportTowerController, TowerDepartureState
from orion.atc_core import AtcSessionIdentity
from orion.atc_operations import FreshnessClass
from orion.atc_runtime import AtcCoreFlow
from orion.communication_contracts import CommunicationProfileId
from orion.golden_takeoff_vertical import GoldenTakeoffVertical
from orion.mixed_conversation import (
    FreeSemanticKind,
    MixedConversationDecomposition,
    MixedDecompositionStatus,
    MixedOperationalIntent,
    MixedProviderStatus,
    build_mixed_composition,
    compose_response_plan,
    mixed_decomposition_tool_definition,
    request_mixed_decomposition,
)
from orion.pilot_phraseology import PilotPhraseologyResolver
from orion.pilot_phraseology_catalog import build_pilot_phraseology_catalog
from orion.planner_contracts import (
    PlannerToolCallsEvent,
    PlannerToolRequest,
    PlannerUsage,
)
from orion.tool_gateway_contracts import ToolArguments


INTERACTION_ID = UUID("12345678-1234-5678-1234-567812345678")
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


class _Run:
    def __init__(self, arguments: dict[str, object]) -> None:
        self.arguments = arguments
        self.cancelled = False

    def next_event(self, **_kwargs):  # noqa: ANN003, ANN202
        return PlannerToolCallsEvent(
            event_id="mixed-event-1",
            calls=(
                PlannerToolRequest(
                    call_id="mixed-call-1",
                    name=mixed_decomposition_tool_definition().name,
                    version="1.0",
                    arguments=ToolArguments(root=self.arguments),
                ),
            ),
            usage=PlannerUsage(
                model_identifier="qwen3.6-35b-a3b",
                provider_request_ids=("provider-response-1",),
                provider_attempts=1,
            ),
        )

    def continue_with_tool_results(self, _results) -> None:  # noqa: ANN001
        raise AssertionError("Mixed decomposition never executes a Core tool")

    def cancel(self) -> None:
        self.cancelled = True


class _Provider:
    provider_id = "fake.mixed"

    def __init__(self, arguments: dict[str, object]) -> None:
        self.run = _Run(arguments)
        self.request = None

    def start(self, request):  # noqa: ANN001, ANN201
        self.request = request
        return self.run


def _decomposition_payload(
    *,
    free: bool = True,
    operational: bool = True,
) -> dict[str, object]:
    return {
        "detected_input_language": "ru-RU",
        "status": "classified",
        "free_semantics": ["greeting"] if free else [],
        "free_source_text": "Добрый день" if free else None,
        "free_response_text": "Добрый день!" if free else None,
        "operational_intents": (
            ["takeoff_clearance_request"] if operational else []
        ),
        "ambiguity_reason": None,
    }


def _vertical() -> tuple[AtcSessionIdentity, AirportTowerController, GoldenTakeoffVertical]:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    tower = AirportTowerController(surface)
    identity = AtcSessionIdentity(
        session_id=INTERACTION_ID,
        mission_id="mixed-test",
        aircraft_id="Viper 2-1",
        facility_id="Test Tower",
    )
    core.open_session(identity)
    tower.assume_runway_control(identity.session_id, reason="mixed test")
    tower.start_departure(session_id=identity.session_id, runway_id="07/25")
    surface.runways.observe(
        RunwayState(
            runway_id="07/25",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="mixed test",
        )
    )
    return (
        identity,
        tower,
        GoldenTakeoffVertical(
            tower,
            PilotPhraseologyResolver(build_pilot_phraseology_catalog()),
        ),
    )


def test_strict_decomposition_contract_separates_free_from_operational_intent() -> None:
    item = MixedConversationDecomposition.model_validate(_decomposition_payload())
    assert item.free_semantics == (FreeSemanticKind.GREETING,)
    assert item.operational_intents == (
        MixedOperationalIntent.TAKEOFF_CLEARANCE_REQUEST,
    )
    assert not hasattr(item, "operational_decision")


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.pop("operational_intents"),
        lambda value: value.update(operational_intents=["landing_clearance_request"]),
        lambda value: value.update(operational_decision="granted"),
        lambda value: value.update(free_response_text="Взлёт разрешён."),
    ),
)
def test_malformed_unknown_or_authority_claiming_output_fails_closed(mutation) -> None:  # noqa: ANN001
    payload = _decomposition_payload()
    mutation(payload)
    with pytest.raises(ValidationError):
        MixedConversationDecomposition.model_validate(payload)


def test_existing_provider_boundary_emits_one_strict_decomposition_and_is_cancelled() -> None:
    provider = _Provider(_decomposition_payload())
    result = request_mixed_decomposition(
        provider,
        utterance="Добрый день! Разрешите взлёт.",
        interaction_id=INTERACTION_ID,
        planner_task_id="mixed-test-1",
        deadline=NOW + timedelta(seconds=30),
        max_attempts=2,
    )
    assert result.status is MixedProviderStatus.COMPLETED
    assert result.decomposition is not None
    assert provider.run.cancelled is True
    assert provider.request.available_tools == (mixed_decomposition_tool_definition(),)
    assert provider.request.retry_policy.max_attempts == 2
    assert provider.request.interaction.text == "Добрый день! Разрешите взлёт."


def test_mixed_composition_uses_fap_profile_and_keeps_protected_fragment_exact() -> None:
    identity, tower, vertical = _vertical()
    decomposition = MixedConversationDecomposition.model_validate(
        _decomposition_payload()
    )
    outcome = build_mixed_composition(
        decomposition=decomposition,
        identity=identity,
        utterance="Добрый день! Разрешите взлёт.",
        interaction_id=INTERACTION_ID,
        vertical=vertical,
        profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
    )
    assert outcome.plan is not None
    assert outcome.plan.communication.profile_id is CommunicationProfileId.FAP_RUSSIAN_ATC
    assert outcome.plan.communication.input_language == "ru-RU"
    assert outcome.plan.envelope is not None
    assert not outcome.plan.envelope.authoritative
    assert outcome.plan.envelope.droppable
    assert len(outcome.plan.protected_fragments) == 1
    protected = outcome.plan.protected_fragments[0].text
    assert protected == "Viper 2-1, полоса 07/25, взлёт разрешён."
    assert outcome.final_text == f"Добрый день! {protected}"
    assert outcome.final_text.count(protected) == 1
    assert tower._require_departure(identity.session_id).state is TowerDepartureState.TAKEOFF_CLEARED


def test_pure_conversation_never_enters_atc_or_phraseology() -> None:
    identity, tower, vertical = _vertical()
    decomposition = MixedConversationDecomposition.model_validate(
        _decomposition_payload(operational=False)
    )
    outcome = build_mixed_composition(
        decomposition=decomposition,
        identity=identity,
        utterance="Добрый день! Как дела?",
        interaction_id=INTERACTION_ID,
        vertical=vertical,
        profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
    )
    assert outcome.golden_result is None
    assert outcome.plan is not None and outcome.plan.protected_fragments == ()
    assert outcome.final_text == "Добрый день!"
    assert tower._require_departure(identity.session_id).state is TowerDepartureState.HOLD_SHORT


def test_profile_mismatch_and_duplicate_protected_fragment_fail_closed() -> None:
    identity, _tower, vertical = _vertical()
    decomposition = MixedConversationDecomposition.model_validate(
        _decomposition_payload()
    )
    with pytest.raises(ValueError, match="profile"):
        build_mixed_composition(
            decomposition=decomposition,
            identity=identity,
            utterance="Добрый день! Разрешите взлёт.",
            interaction_id=INTERACTION_ID,
            vertical=vertical,
            profile_id=CommunicationProfileId.NATO_MILITARY,
        )
    outcome = build_mixed_composition(
        decomposition=decomposition,
        identity=identity,
        utterance="Добрый день! Разрешите взлёт.",
        interaction_id=INTERACTION_ID,
        vertical=vertical,
        profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
    )
    assert outcome.plan is not None
    duplicate = outcome.plan.model_copy(
        update={
            "protected_fragments": (
                outcome.plan.protected_fragments[0],
                outcome.plan.protected_fragments[0],
            )
        }
    )
    with pytest.raises(ValueError, match="duplicate"):
        compose_response_plan(duplicate)
