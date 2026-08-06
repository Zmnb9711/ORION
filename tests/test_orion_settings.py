from fastapi.testclient import TestClient

from orion.app import app
from orion.orion_settings import (
    CommunicationMode,
    OrionSettingsStore,
    OrionSettingsUpdate,
    ResponseDetail,
    UnpreparedMissionAction,
    VoiceGender,
)


def test_settings_store_updates_only_orion_behavior() -> None:
    store = OrionSettingsStore()
    updated = store.update(
        OrionSettingsUpdate(
            response_detail=ResponseDetail.BRIEF,
            minimize_console_after_launch=True,
            assistant_name="Wingman",
            communication_mode=CommunicationMode.AVIATION_ENGLISH,
            voice_gender=VoiceGender.FEMALE,
            voice_variant="aurora",
            microphone_id="windows-default",
            random_conversations=True,
            unprepared_mission_action=UnpreparedMissionAction.PREPARE_COPY,
        )
    )

    assert updated.response_detail is ResponseDetail.BRIEF
    assert updated.minimize_console_after_launch is True
    assert updated.assistant_name == "Wingman"
    assert updated.communication_mode is CommunicationMode.AVIATION_ENGLISH
    assert updated.voice_gender is VoiceGender.FEMALE
    assert updated.voice_variant == "aurora"
    assert updated.microphone_id == "windows-default"
    assert updated.random_conversations is True
    assert updated.unprepared_mission_action is UnpreparedMissionAction.PREPARE_COPY

    # ORION settings must not expose controls for DCS, VR, OpenXR or a manual callsign.
    assert not hasattr(updated, "vr_resolution")
    assert not hasattr(updated, "openxr_runtime")
    assert not hasattr(updated, "dcs_graphics")
    assert not hasattr(updated, "pilot_callsign")


def test_settings_help_contains_approved_tooltips() -> None:
    client = TestClient(app)
    response = client.get("/v1/settings/help")

    assert response.status_code == 200
    payload = response.json()
    modes = {item["mode"]: item for item in payload["communication_modes"]}

    assert set(modes) == {
        "aviation_english",
        "aviation_russian",
        "free_communication",
    }
    assert "фразеологии" in modes["aviation_english"]["description"]
    assert "естественным языком" in modes["free_communication"]["description"]
    assert "Оригинальный файл миссии не изменяется" in payload["mission_pack"][
        "safety_notice"
    ]


def test_settings_api_routes_are_available() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]

    assert "/v1/settings" in paths
    assert "/v1/settings/reset" in paths
    assert "/v1/settings/help" in paths
