from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from orion.communication_profile_packs import CommunicationProfileService, CommunicationProfileStore
from orion.desktop_launcher_field_fixed import FieldFixedAudioLauncher
from orion.launcher_communication_profiles import (
    COMMUNICATION_PROFILE_COLUMNS,
    COMMUNICATION_PROFILE_WIDTHS,
    PROFILE_LABELS,
    PROFILE_ORDER,
    LauncherCommunicationProfilesMixin,
    format_profile_details,
    parse_profile_view_state,
    profile_row_text,
)


def _payload(tmp_path) -> dict[str, object]:  # noqa: ANN001
    service = CommunicationProfileService(CommunicationProfileStore(tmp_path / "profiles"))
    service.select_profile(service.cards()[1].profile_id)
    cards = service.cards()
    return {
        "configured_profile_id": "FAA_US",
        "effective_profile_id": None,
        "configured_pack_version": "0.1.0",
        "effective_pack_version": None,
        "registry_configured": False,
        "registry_status": "UPDATE SOURCE NOT CONFIGURED",
        "profiles": [item.model_dump(mode="json") for item in cards],
    }


def test_exact_approved_rows_and_radio_selection_model(tmp_path) -> None:  # noqa: ANN001
    assert PROFILE_ORDER == ("ICAO", "FAA_US", "NATO_MILITARY", "FAP_RUSSIAN_ATC")
    assert PROFILE_LABELS == ("ICAO", "FAA US", "NATO Military", "FAP Russian ATC")
    state = parse_profile_view_state(_payload(tmp_path))
    assert [card.display_name for card in state.profiles] == list(PROFILE_LABELS)
    assert [card.profile_id.value for card in state.profiles if card.selected] == ["FAA_US"]


def test_inconsistent_or_multiple_selection_fails_closed(tmp_path) -> None:  # noqa: ANN001
    payload = _payload(tmp_path)
    payload["profiles"][0]["selected"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="exactly one"):
        parse_profile_view_state(payload)
    payload = _payload(tmp_path)
    payload["profiles"][0]["future_field"] = True  # type: ignore[index]
    with pytest.raises(ValidationError):
        parse_profile_view_state(payload)


def test_row_displays_version_verification_readiness_coverage_languages_and_update(tmp_path) -> None:  # noqa: ANN001
    state = parse_profile_view_state(_payload(tmp_path))
    rendered = profile_row_text(state.profiles[1])
    assert rendered[0] == "FAA US"
    assert rendered[1] == "0.1.0"
    assert rendered[2] == "READY"
    assert rendered[3] == "EXPERIMENTAL / RESEARCH_ONLY"
    assert "AIRPORT_ATC: CONTENT_NOT_INSTALLED" in rendered[4]
    assert rendered[5] == "Not installed"
    assert rendered[6] == "NO REGISTRY"


def test_details_distinguish_three_status_axes_and_source_limitations(tmp_path) -> None:  # noqa: ANN001
    service = CommunicationProfileService(CommunicationProfileStore(tmp_path / "profiles"))
    text = format_profile_details(service.details(service.cards()[0].profile_id))
    assert "SOURCE REGISTRY STATUS\nPARTIAL" in text
    assert "PACK CONTENT VERIFICATION\nPARTIAL" in text
    assert "RUNTIME READINESS\nRESEARCH_ONLY" in text
    assert "Licensing restricted" in text
    assert "No production phraseology is bundled" in text


def test_launcher_surface_has_no_operational_response_language_selector() -> None:
    source = inspect.getsource(LauncherCommunicationProfilesMixin)
    assert "ttk.Radiobutton" in source
    assert "CHECK FOR UPDATES" in source
    assert "ROLL BACK" in source
    assert "Response Language" not in source
    assert "response_language" not in source
    assert issubclass(FieldFixedAudioLauncher, LauncherCommunicationProfilesMixin)


def test_profile_table_is_compact_and_has_no_horizontal_scroller() -> None:
    assert len(COMMUNICATION_PROFILE_COLUMNS) == 7
    assert sum(COMMUNICATION_PROFILE_WIDTHS) <= 90
    source = inspect.getsource(LauncherCommunicationProfilesMixin._build_communication_profile_section)
    assert "wraplength=820" in source
    assert "askyesno" in source
    assert "xscrollcommand" not in source
    assert "Treeview" not in source
