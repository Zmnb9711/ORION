from __future__ import annotations

from uuid import UUID

import pytest

from orion.airport_surface import RunwayAvailability, RunwayState
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.airport_tower_runtime import AirportTowerController, TowerDepartureState
from orion.atc_core import AtcSessionIdentity
from orion.atc_operations import FreshnessClass
from orion.atc_runtime import AtcCoreFlow
from orion.golden_takeoff_vertical import (
    GoldenTakeoffStatus,
    GoldenTakeoffVertical,
    TakeoffIntentStatus,
    classify_takeoff_intent,
)
from orion.pilot_phraseology import PilotPhraseologyResolver
from orion.pilot_phraseology_catalog import build_pilot_phraseology_catalog


CALLSIGN = "Viper 2-1"
RUNWAY = "07/25"


def _vertical(
    availability: RunwayAvailability | None,
    *,
    freshness: FreshnessClass = FreshnessClass.FRESH,
) -> tuple[AtcSessionIdentity, AirportTowerController, GoldenTakeoffVertical]:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    tower = AirportTowerController(surface)
    identity = AtcSessionIdentity(
        session_id=UUID("12345678-1234-5678-1234-567812345678"),
        mission_id="golden-test",
        aircraft_id=CALLSIGN,
        facility_id="Test Tower",
    )
    core.open_session(identity)
    tower.assume_runway_control(identity.session_id, reason="test fixture")
    tower.start_departure(session_id=identity.session_id, runway_id=RUNWAY)
    if availability is not None:
        surface.runways.observe(
            RunwayState(
                runway_id=RUNWAY,
                availability=availability,
                freshness=freshness,
                reason="test fixture",
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


@pytest.mark.parametrize(
    "utterance,language",
    (
        ("Разрешите взлёт.", "ru-RU"),
        ("Можно взлетать?", "ru-RU"),
        ("Башня, готов к взлёту.", "ru-RU"),
        ("Готов к взлёту, разрешите взлёт.", "ru-RU"),
        ("Запрашиваю разрешение на взлёт.", "ru-RU"),
        ("Tower, request takeoff clearance.", "en-US"),
        ("Ready for takeoff.", "en-US"),
        ("Request takeoff.", "en-US"),
        ("Tower, Viper 2-1 ready for departure.", "en-US"),
    ),
)
def test_approved_ru_en_corpus_is_bounded_takeoff_intent(
    utterance: str,
    language: str,
) -> None:
    intent = classify_takeoff_intent(utterance)
    assert intent.status is TakeoffIntentStatus.RECOGNIZED
    assert intent.language == language
    assert intent.kind is not None


@pytest.mark.parametrize(
    "utterance",
    (
        "Добрый день! Разрешите взлёт.",
        "Разрешите взлёт и скажите частоту.",
        "После взлёта какая будет частота?",
        "Расскажи про взлёт.",
        "Почему мне не разрешили взлёт?",
        "Если разрешат взлёт, что делать дальше?",
        "Какие сегодня новости перед взлётом?",
        "Как дела перед взлётом?",
    ),
)
def test_mixed_or_discursive_takeoff_cues_are_never_recognized_as_pure(
    utterance: str,
) -> None:
    assert classify_takeoff_intent(utterance).status is not TakeoffIntentStatus.RECOGNIZED


def test_permitted_request_uses_existing_atc_and_preserves_protected_slots() -> None:
    identity, tower, vertical = _vertical(RunwayAvailability.CLEAR)
    result = vertical.handle(
        identity=identity,
        utterance="Tower, Viper 2-1 ready for departure.",
    )
    assert result.status is GoldenTakeoffStatus.GRANTED
    assert result.decision is not None
    assert result.decision.instruction is not None
    assert result.decision.instruction.semantic_action == "takeoff_clearance"
    assert result.decision.instruction.parameters == {"runway_id": RUNWAY}
    assert tower._require_departure(identity.session_id).state is TowerDepartureState.TAKEOFF_CLEARED
    assert result.semantic_unit is not None
    assert {
        item.key: (item.kind.value, item.value, item.unit)
        for item in result.semantic_unit.protected_values
    } == {
        "atc.callsign": ("callsign", CALLSIGN, None),
        "atc.runway_id": ("runway", RUNWAY, None),
    }
    assert len(result.semantic_unit.provenance) == 1
    assert result.fragment is not None
    assert result.fragment.text == "Viper 2-1, runway 07/25, cleared for takeoff."
    assert result.fragment.semantic_unit == result.semantic_unit


@pytest.mark.parametrize("language", ["ru", "en"])
def test_occupied_runway_is_hold_and_never_becomes_clearance(language: str) -> None:
    identity, tower, vertical = _vertical(RunwayAvailability.OCCUPIED)
    utterance = "Разрешите взлёт." if language == "ru" else "Request takeoff."
    result = vertical.handle(identity=identity, utterance=utterance)
    assert result.status is GoldenTakeoffStatus.HOLD
    assert result.decision is not None and result.decision.instruction is None
    assert result.decision.reason_code == "runway_not_clear"
    assert tower._require_departure(identity.session_id).state is TowerDepartureState.HOLD_SHORT
    assert result.resolution is not None
    assert result.resolution.selected_entry_id == "atc-takeoff-hold"
    assert result.fragment is not None
    assert "cleared for takeoff" not in result.fragment.text
    assert "взлёт разрешён" not in result.fragment.text


def test_missing_runway_observation_is_unavailable_not_permission() -> None:
    identity, tower, vertical = _vertical(None, freshness=FreshnessClass.UNKNOWN)
    result = vertical.handle(identity=identity, utterance="Разрешите взлёт.")
    assert result.status is GoldenTakeoffStatus.UNAVAILABLE
    assert result.decision is not None
    assert result.decision.reason_code == "runway_context_unavailable"
    assert result.resolution is not None
    assert result.resolution.selected_entry_id == "atc-takeoff-context-unavailable"
    assert tower._require_departure(identity.session_id).state is TowerDepartureState.HOLD_SHORT


@pytest.mark.parametrize("utterance", ["Какая погода?", "Report weather."])
def test_unsupported_input_stops_before_atc_and_pilot(utterance: str) -> None:
    identity, tower, vertical = _vertical(RunwayAvailability.CLEAR)
    result = vertical.handle(identity=identity, utterance=utterance)
    assert result.status is GoldenTakeoffStatus.UNSUPPORTED
    assert result.decision is result.semantic_unit is result.resolution is result.fragment is None
    assert tower._require_departure(identity.session_id).state is TowerDepartureState.HOLD_SHORT


@pytest.mark.parametrize("utterance", ["Башня, готов.", "Tower, ready."])
def test_ambiguous_input_requests_clarification_without_atc_decision(
    utterance: str,
) -> None:
    identity, tower, vertical = _vertical(RunwayAvailability.CLEAR)
    result = vertical.handle(identity=identity, utterance=utterance)
    assert result.status is GoldenTakeoffStatus.CLARIFICATION_REQUIRED
    assert result.intent.status is TakeoffIntentStatus.AMBIGUOUS
    assert result.decision is None
    assert result.resolution is not None
    assert result.resolution.selected_entry_id == "general-say-again-fap"
    assert result.fragment is not None
    assert tower._require_departure(identity.session_id).state is TowerDepartureState.HOLD_SHORT


@pytest.mark.parametrize(
    "utterance",
    [
        "Не разрешайте взлёт.",
        "Tower, cancel takeoff request.",
        "Взлёт.",
        "Takeoff.",
    ],
)
def test_conflicting_or_incomplete_takeoff_language_never_grants(
    utterance: str,
) -> None:
    identity, tower, vertical = _vertical(RunwayAvailability.CLEAR)
    result = vertical.handle(identity=identity, utterance=utterance)
    assert result.status is GoldenTakeoffStatus.CLARIFICATION_REQUIRED
    assert result.decision is None
    assert tower._require_departure(identity.session_id).state is TowerDepartureState.HOLD_SHORT
