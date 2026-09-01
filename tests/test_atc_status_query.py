from __future__ import annotations

from uuid import UUID

import pytest

from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_status_query import (
    ATC_STATUS_SEMANTIC_MEANING,
    AtcStatusIntentStatus,
    PersistentAtcSessionCoordinator,
    classify_atc_status_query,
)
from orion.interaction_contracts import PresentationMode


@pytest.mark.parametrize(
    "utterance,language",
    (
        ("Какой диспетчер сейчас управляет моим полётом?", "ru-RU"),
        ("КТО СЕЙЧАС УПРАВЛЯЕТ МОИМ ПОЛЕТОМ!!!", "ru-RU"),
        ("Who currently controls my flight?", "en-US"),
        (" Which controller currently controls my flight. ", "en-US"),
    ),
)
def test_whole_utterance_status_recognizer_accepts_only_approved_forms(
    utterance: str,
    language: str,
) -> None:
    intent = classify_atc_status_query(utterance)
    assert intent.status is AtcStatusIntentStatus.RECOGNIZED
    assert intent.language == language


@pytest.mark.parametrize(
    "utterance",
    (
        "Он спросил: кто сейчас управляет моим полётом?",
        "Я не спрашиваю, кто сейчас управляет моим полётом",
        "Добрый день! Кто сейчас управляет моим полётом?",
        "Кто сейчас управляет моим полётом и какая частота?",
        "Кто диспетчер?",
        "Какой диспетчер?",
        "Кто управляет?",
        "Tower, who currently controls my flight and report frequency?",
    ),
)
def test_status_recognizer_rejects_mixed_meta_and_ambiguous_forms(
    utterance: str,
) -> None:
    assert classify_atc_status_query(utterance).status is AtcStatusIntentStatus.UNSUPPORTED


def _create_bound_session(
    coordinator: PersistentAtcSessionCoordinator,
    *,
    main_session_id: str = "voice-main",
    run_id: str = "run-one",
):  # noqa: ANN202
    return coordinator.get_or_create_takeoff_session(
        main_session_id=main_session_id,
        run_id=run_id,
        callsign="Viper 2-1",
        runway_id="07/25",
        facility_id="Golden Tower",
    )


def test_status_reads_same_persistent_session_and_does_not_mutate_atc_truth() -> None:
    coordinator = PersistentAtcSessionCoordinator()
    identity, vertical, created = _create_bound_session(coordinator)
    assert created is True
    golden = vertical.handle(identity=identity, utterance="Разрешите взлёт.")
    coordinator.synchronize_takeoff_result(
        main_session_id="voice-main",
        run_id="run-one",
        result=golden,
    )
    before = coordinator.service.status(identity.session_id).model_dump(mode="json")
    outcome = coordinator.query_status(
        main_session_id="voice-main",
        run_id="run-one",
        interaction_id=UUID("12345678-1234-5678-1234-567812345678"),
        language="ru-RU",
    )
    after = coordinator.service.status(identity.session_id).model_dump(mode="json")

    assert outcome.result.session_id == identity.session_id
    assert outcome.result.controller_agency is ControllerAgency.AIRPORT_TOWER
    assert outcome.result.procedural_state == "takeoff_cleared"
    assert outcome.result.runtime_revision_before == outcome.result.runtime_revision_after
    assert outcome.result.atc_truth_unchanged is True
    assert before == after
    assert outcome.semantic_unit.semantic_meaning == ATC_STATUS_SEMANTIC_MEANING
    assert outcome.semantic_response.presentation_mode is PresentationMode.VERBATIM
    assert outcome.radio_entity_id == "orion.atc.airport_tower"
    assert "Golden Tower" not in outcome.final_text

    same_identity, same_vertical, created_again = _create_bound_session(coordinator)
    assert created_again is False
    assert same_identity.session_id == identity.session_id
    assert same_vertical is vertical


def test_missing_session_and_missing_flight_traffic_owner_are_unavailable() -> None:
    coordinator = PersistentAtcSessionCoordinator()
    missing = coordinator.query_status(
        main_session_id="missing-main",
        run_id="missing-run",
        interaction_id=UUID("12345678-1234-5678-1234-567812345678"),
        language="en-US",
    )
    assert missing.result.session_id is None
    assert missing.result.authority_available is False
    assert missing.semantic_unit.status == "unavailable"
    assert missing.radio_entity_id == "orion.atc.status"

    identity, _vertical, _created = _create_bound_session(coordinator)
    coordinator.service.core.authority.release(
        session_id=identity.session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.AIRPORT_TOWER,
    )
    coordinator.service.core.authority.claim(
        session_id=identity.session_id,
        scope=ControllerAuthorityScope.SURFACE_MOVEMENT,
        agency=ControllerAgency.AIRPORT_GROUND,
        reason="unrelated scope must not answer flight traffic query",
    )
    unavailable = coordinator.query_status(
        main_session_id="voice-main",
        run_id="run-one",
        interaction_id=UUID("22345678-1234-5678-1234-567812345678"),
        language="en-US",
    )
    assert unavailable.result.session_id == identity.session_id
    assert unavailable.result.controller_agency is None
    assert unavailable.result.authority_available is False
    assert unavailable.semantic_unit.status == "unavailable"
    assert "airport_ground" not in unavailable.final_text


def test_bindings_do_not_leak_and_release_closes_only_the_target_session() -> None:
    coordinator = PersistentAtcSessionCoordinator()
    first, _vertical, _created = _create_bound_session(coordinator)
    second, _vertical, _created = _create_bound_session(
        coordinator,
        main_session_id="voice-other",
        run_id="run-other",
    )
    assert first.session_id != second.session_id

    released = coordinator.release_main_session("voice-main")
    assert released == (first.session_id,)
    assert coordinator.service.sessions.get(first.session_id) is None
    assert coordinator.service.sessions.get(second.session_id) is not None
    assert coordinator.bound_session_id(
        main_session_id="voice-other", run_id="run-other"
    ) == second.session_id
