from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from orion.aircraft_identity_query import (
    AIRCRAFT_IDENTITY_CAPABILITY,
    AIRCRAFT_IDENTITY_RADIO_ENTITY,
    AIRCRAFT_IDENTITY_SEMANTIC_MEANING,
    AircraftIdentityFormulationError,
    AircraftIdentityFormulationService,
    AircraftIdentityIntentStatus,
    AircraftIdentityQueryService,
    AircraftIdentityQueryStatus,
    classify_aircraft_identity_query,
)
from orion.atc_status_query import PersistentAtcSessionCoordinator
from orion.interaction_contracts import (
    PresentationMode,
    SemanticFact,
    SemanticFactKind,
    SemanticResponse,
)
from orion.planner_contracts import PlannerFinalResponseEvent, PlannerUsage
from orion.live_telemetry_store import LiveTelemetryStore
from orion.mission import MissionSnapshot
from orion.mission_bridge_ingest import MissionBridgeState
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.world_model import WorldModelFacade
from orion.world_model_contracts import WorldFactAuthority, WorldFactSource, WorldFactStatus


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INTERACTION_ID = UUID("12345678-1234-5678-1234-567812345678")


@dataclass
class _MissionOwner:
    snapshot: MissionSnapshot | None = None

    def get(self) -> MissionSnapshot | None:
        return self.snapshot


@dataclass
class _BridgeOwner:
    snapshot: MissionBridgeState = field(default_factory=MissionBridgeState)

    def state(self) -> MissionBridgeState:
        return self.snapshot.model_copy(deep=True)


def _store(
    aircraft_type: str | None = "FA-18C_hornet",
    *,
    age_seconds: float = 1,
) -> LiveTelemetryStore:
    store = LiveTelemetryStore()
    if aircraft_type is None:
        store.observe_heartbeat(received_at=NOW - timedelta(seconds=age_seconds))
        return store
    store.set(
        TelemetryEnvelope(
            sequence=1,
            state=AircraftState(
                aircraft_type=aircraft_type,
                position=Position(latitude=42.1, longitude=41.2, altitude_m=1000),
                heading_deg=137,
                true_airspeed_mps=145,
            ),
        ),
        received_at=NOW - timedelta(seconds=age_seconds),
    )
    return store


def _service(store: LiveTelemetryStore) -> AircraftIdentityQueryService:
    return AircraftIdentityQueryService(
        WorldModelFacade(
            telemetry=store,
            mission=_MissionOwner(),
            mission_bridge=_BridgeOwner(),
            clock=lambda: NOW,
        )
    )


class _FormulationRun:
    def __init__(self, request, response: SemanticResponse) -> None:  # noqa: ANN001
        self.request = request
        self.response = response.model_copy(
            update={"interaction_id": request.interaction.interaction_id}
        )

    def next_event(self, **_kwargs):  # noqa: ANN003, ANN202
        return PlannerFinalResponseEvent(
            event_id="aircraft-formulation-final",
            response=self.response,
            usage=PlannerUsage(
                model_identifier="qwen3.6-35b-a3b",
                provider_request_ids=("qwen-aircraft-1",),
                provider_attempts=1,
                provider_latency_ms=7,
            ),
        )

    def continue_with_tool_results(self, _results) -> None:  # noqa: ANN001
        raise AssertionError("Aircraft formulation has no tools")

    def cancel(self) -> None:
        return None


class _FormulationProvider:
    provider_id = "fake.qwen"

    def __init__(self, recommendation: str, **response_updates) -> None:  # noqa: ANN003
        self.recommendation = recommendation
        self.response_updates = response_updates
        self.requests = []

    def start(self, request):  # noqa: ANN001, ANN201
        self.requests.append(request)
        response = SemanticResponse(
            interaction_id=request.interaction.interaction_id,
            presentation_mode=PresentationMode.NATURALIZE,
            recommendation=self.recommendation,
        ).model_copy(update=self.response_updates)
        return _FormulationRun(request, response)


def _formulate(
    store: LiveTelemetryStore,
    recommendation: str,
    *,
    language: str = "ru-RU",
    **response_updates,
):  # noqa: ANN003, ANN202
    provider = _FormulationProvider(recommendation, **response_updates)
    outcome = AircraftIdentityFormulationService(query=_service(store)).execute(
        provider=provider,
        interaction_id=INTERACTION_ID,
        utterance=(
            "В каком самолёте я нахожусь?"
            if language == "ru-RU"
            else "What aircraft am I in?"
        ),
        language=language,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
    )
    return outcome, provider


@pytest.mark.parametrize(
    "utterance,language",
    (
        ("В каком самолёте я нахожусь?", "ru-RU"),
        ("  В КАКОМ САМОЛЕТЕ Я НАХОЖУСЬ!!! ", "ru-RU"),
        ("На каком самолёте я сейчас нахожусь?", "ru-RU"),
        ("Какой у меня самолёт?", "ru-RU"),
        ("What aircraft am I in?", "en-US"),
        (" WHAT AIRCRAFT AM I FLYING!!! ", "en-US"),
        ("Which aircraft am I flying?", "en-US"),
    ),
)
def test_whole_utterance_aircraft_identity_recognizer(
    utterance: str,
    language: str,
) -> None:
    intent = classify_aircraft_identity_query(utterance)
    assert intent.status is AircraftIdentityIntentStatus.RECOGNIZED
    assert intent.language == language


@pytest.mark.parametrize(
    "utterance",
    (
        "Привет, в каком самолёте я нахожусь?",
        "В каком самолёте я нахожусь и как включить TACAN?",
        "Он спросил: в каком самолёте я нахожусь?",
        "Если бы я был в F-16, какой это был бы самолёт?",
        "Какой самолёт летит справа?",
        "Что это за самолёт на радаре?",
        "Что ты знаешь про F/A-18?",
        "Я в F/A-18 или F-16?",
        "Какой это самолёт?",
    ),
)
def test_aircraft_identity_recognizer_rejects_mixed_and_ambiguous_forms(
    utterance: str,
) -> None:
    intent = classify_aircraft_identity_query(utterance)
    assert intent.status is AircraftIdentityIntentStatus.UNSUPPORTED


@pytest.mark.parametrize(
    "raw,display",
    (
        ("FA-18C_hornet", "F/A-18C Hornet"),
        ("A-10C_2", "A-10C II Tank Killer"),
    ),
)
def test_live_known_aircraft_uses_world_model_truth_and_existing_normalization(
    raw: str,
    display: str,
) -> None:
    store = _store(raw)
    generation_before = store.snapshot().generation
    result = _service(store).resolve()
    generation_after = store.snapshot().generation

    assert result.status is AircraftIdentityQueryStatus.AVAILABLE
    assert result.semantic_meaning == AIRCRAFT_IDENTITY_SEMANTIC_MEANING
    assert result.raw_aircraft_id == raw
    assert result.display_name == display
    assert result.fact_status is WorldFactStatus.KNOWN
    assert result.source is WorldFactSource.DCS_EXPORT
    assert result.authority is WorldFactAuthority.AUTHORITATIVE
    assert result.age_seconds == 1
    assert result.generation == generation_before == generation_after


def test_qwen_naturalizes_only_a_marker_and_core_binds_exact_live_fact() -> None:
    outcome, provider = _formulate(
        _store("FA-18C_hornet"),
        "Вы сейчас находитесь в {{aircraft_identity}}.",
    )

    assert outcome.semantic_response.capability == AIRCRAFT_IDENTITY_CAPABILITY
    assert outcome.semantic_response.presentation_mode is PresentationMode.VERBATIM
    assert outcome.semantic_response.authoritative_facts[0].value == "FA-18C_hornet"
    assert outcome.semantic_response.authoritative_facts[0].kind is SemanticFactKind.AUTHORITATIVE
    assert outcome.semantic_response.derived_results[0].value == "F/A-18C Hornet"
    assert outcome.semantic_response.derived_results[0].kind is SemanticFactKind.DERIVED
    assert outcome.final_text == "Вы сейчас находитесь в F/A-18C Hornet."
    assert outcome.radio_entity_id == AIRCRAFT_IDENTITY_RADIO_ENTITY
    assert outcome.qwen_call_count == 1
    assert outcome.qwen_fact_authority is False
    assert outcome.qwen_response_ids == ("qwen-aircraft-1",)
    assert len(provider.requests) == 1
    assert provider.requests[0].allowed_capabilities == ()
    assert provider.requests[0].available_tools == ()


def test_live_unknown_raw_aircraft_is_sanitized_without_inference() -> None:
    outcome, _provider = _formulate(
        _store("F-16C_50"),
        "Your current aircraft is {{aircraft_identity}}.",
        language="en-US",
    )
    assert outcome.result.status is AircraftIdentityQueryStatus.AVAILABLE
    assert outcome.result.raw_aircraft_id == "F-16C_50"
    assert outcome.result.display_name == "F-16C 50"
    assert "Viper" not in outcome.final_text
    assert outcome.final_text == "Your current aircraft is F-16C 50."


@pytest.mark.parametrize(
    "store,expected_reason,expected_status",
    (
        (_store(None), "no_player_aircraft", WorldFactStatus.UNAVAILABLE),
        (_store("FA-18C_hornet", age_seconds=6), "source_stale", WorldFactStatus.STALE),
        (LiveTelemetryStore(), "source_not_connected", WorldFactStatus.UNAVAILABLE),
    ),
)
def test_absent_no_player_and_stale_dcs_are_unavailable_without_fixture_fallback(
    store: LiveTelemetryStore,
    expected_reason: str,
    expected_status: WorldFactStatus,
) -> None:
    result = _service(store).resolve()
    assert result.status is AircraftIdentityQueryStatus.UNAVAILABLE
    assert result.fact_status is expected_status
    assert result.raw_aircraft_id is None
    assert result.display_name is None
    assert result.unavailable_reason == expected_reason


def test_unavailable_core_fact_allows_wording_but_no_qwen_aircraft_inference() -> None:
    outcome, _provider = _formulate(
        LiveTelemetryStore(),
        "К сожалению, {{aircraft_unavailable}}.",
    )
    assert outcome.result.status is AircraftIdentityQueryStatus.UNAVAILABLE
    assert outcome.semantic_response.authoritative_facts == ()
    assert outcome.semantic_response.derived_results == ()
    assert outcome.semantic_response.unavailable_inputs[0].reason == "source_not_connected"
    assert outcome.final_text == (
        "К сожалению, данные о текущем самолёте из DCS недоступны."
    )
    assert "F/A-18" not in outcome.final_text


def test_aircraft_replacement_and_no_player_clear_follow_current_store_without_cache() -> None:
    store = _store("FA-18C_hornet")
    service = _service(store)
    first = service.resolve()
    assert first.display_name == "F/A-18C Hornet"

    store.set(
        TelemetryEnvelope(
            sequence=2,
            state=AircraftState(
                aircraft_type="A-10C_2",
                position=Position(latitude=42.1, longitude=41.2, altitude_m=1000),
                heading_deg=137,
                true_airspeed_mps=145,
            ),
        ),
        received_at=NOW - timedelta(seconds=1),
    )
    second = service.resolve()
    assert second.display_name == "A-10C II Tank Killer"
    assert second.generation != first.generation

    store.observe_heartbeat(received_at=NOW)
    cleared = service.resolve()
    assert cleared.status is AircraftIdentityQueryStatus.UNAVAILABLE
    assert cleared.unavailable_reason == "no_player_aircraft"
    assert cleared.raw_aircraft_id is None


def test_non_dcs_aircraft_fact_fails_closed() -> None:
    snapshot = WorldModelFacade(
        telemetry=_store(),
        mission=_MissionOwner(),
        mission_bridge=_BridgeOwner(),
        clock=lambda: NOW,
    ).ownship()
    wrong_source = snapshot.model_copy(
        update={
            "aircraft": snapshot.aircraft.model_copy(
                update={"source": WorldFactSource.MISSION_STORE}
            )
        }
    )

    class _WrongSource:
        def ownship(self):  # noqa: ANN201
            return wrong_source

    result = AircraftIdentityQueryService(_WrongSource()).resolve()
    assert result.status is AircraftIdentityQueryStatus.UNAVAILABLE
    assert result.unavailable_reason == "non_live_dcs_source"
    assert result.raw_aircraft_id is None


def test_query_does_not_mutate_atc_state_or_depend_on_tool_gateway() -> None:
    atc = PersistentAtcSessionCoordinator()
    identity, _vertical, _created = atc.get_or_create_takeoff_session(
        main_session_id="voice-main",
        run_id="run-one",
        callsign="Viper 2-1",
        runway_id="07/25",
        facility_id="Golden Tower",
    )
    before = atc.service.status(identity.session_id).model_dump(mode="json")
    result = _service(_store()).resolve()
    after = atc.service.status(identity.session_id).model_dump(mode="json")

    assert result.status is AircraftIdentityQueryStatus.AVAILABLE
    assert before == after
    source = Path("orion/aircraft_identity_query.py").read_text(encoding="utf-8")
    assert "tool_gateway" not in source


@pytest.mark.parametrize(
    "recommendation",
    (
        "Вы сейчас находитесь в F-16C.",
        "Вы сейчас находитесь в {{aircraft_identity}}, не в F-16C.",
        "Вы сейчас находитесь в {{aircraft_identity}} и летите курсом 137.",
        "Вы сейчас находитесь в {{aircraft_unavailable}}.",
        "Your current aircraft is {{aircraft_identity}}.",
    ),
)
def test_qwen_cannot_invent_override_or_extend_core_aircraft_fact(
    recommendation: str,
) -> None:
    with pytest.raises(AircraftIdentityFormulationError):
        _formulate(_store("FA-18C_hornet"), recommendation)


def test_qwen_cannot_claim_fact_authority_in_formulation_response() -> None:
    with pytest.raises(AircraftIdentityFormulationError):
        _formulate(
            _store("FA-18C_hornet"),
            "Вы сейчас находитесь в {{aircraft_identity}}.",
            derived_results=(
                SemanticFact(
                    key="flight.current_aircraft_identity",
                    value="F-16C Viper",
                    kind=SemanticFactKind.DERIVED,
                ),
            ),
        )
